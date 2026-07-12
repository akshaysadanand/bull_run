"""Multi-turn chat with MCP-based web search and scrape for stock news analysis."""

import asyncio
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from openai import OpenAI
from datetime import datetime

from utils.prompts import SystemPrompts

logger = logging.getLogger(__name__)

CURRENT_DATE = datetime.now().strftime("%B %d, %Y")

MCP_SERVER_DIR = Path.home() / "Projects" / "web-search-MCP"
MAX_SEARCH_ITERATIONS = 10
MAX_CHAT_TURNS = 10
MAX_SEARCHES = 5  # Hard cap on searxng_search calls per question
MAX_PARALLEL_SEARCHES = 2  # Max searxng_search calls the LLM can make in a single turn
MAX_SCRAPE_CONTENT_LENGTH = 10000  # Truncate scraped page content to limit context size

TEMPERATURE = 1.0
TOP_P = 0.95
PRESENCE_PENALTY = 0.5
MAX_TOKENS = 10000  # Max tokens for LLM responses (increased for research-heavy tasks)

def _strip_tool_call_xml(text: str) -> str:
    """Strip raw tool call XML (`<tool_call>...</tool_call>`) from LLM content.

    Some LLMs include the raw function-calling syntax in the content field
    alongside structured tool_calls. This strips those artifacts.

    Matches ANY content between the sentinel characters `<tool_call>` (U+2458) and
    `</tool_call>` (U+2459), regardless of internal XML structure.
    """
    # Match anything between sentinels: `<tool_call> ... _` (handles newlines, malformed XML, etc.)
    text = re.sub(r'\u2458.*?\u2459', '', text, flags=re.DOTALL)
    # Match unclosed `<tool_call>` sentinel — strip everything from sentinel to end of string
    text = re.sub(r'\u2458.*$', '', text, flags=re.DOTALL | re.MULTILINE)
    
    # Also strip literal <tool_call> XML blocks
    text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Match unclosed literal <tool_call>
    text = re.sub(r'<tool_call>.*$', '', text, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)
    
    return text.strip()


def strip_thinking_tags(text: str) -> tuple[str, str]:
    """Extract and strip chain-of-thought tags from LLM output.

    Handles <think>...</think>, <thinking>...</thinking>, and trailing
    unclosed <think> blocks.

    Args:
        text: Raw LLM output text.

    Returns:
        Tuple of (cleaned_text, thinking_content). thinking_content is empty
        string if no thinking tags found.
    """
    # Extract thinking content from closed tags
    thinking_parts = re.findall(r'<think>(.*?)</think>', text, flags=re.DOTALL | re.IGNORECASE)
    thinking_parts += re.findall(r'<thinking>(.*?)</thinking>', text, flags=re.DOTALL | re.IGNORECASE)
    # Catch trailing unclosed <think> blocks — negative lookahead ensures we skip
    # blocks that already have a closing tag (avoiding double-extraction)
    trailing = re.findall(r'<think>(?!.*</think>)(.*?)$', text, flags=re.DOTALL | re.IGNORECASE)
    trailing += re.findall(r'<thinking>(?!.*</thinking>)(.*?)$', text, flags=re.DOTALL | re.IGNORECASE)
    thinking_parts += trailing

    thinking = "\n".join(p.strip() for p in thinking_parts if p.strip())

    # Strip all thinking blocks from the text
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<thinking>.*?</thinking>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'\s*<think>.*$', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'\s*<thinking>.*$', '', cleaned, flags=re.DOTALL | re.IGNORECASE)

    return cleaned.strip(), thinking


class StreamingThinkingParser:
    """Incrementally separates thinking tags from content during streaming.

    Tracks state (inside/outside thinking tags) and accumulates
    thinking vs. visible content separately — no regex needed per chunk.
    Handles <think>...</think>, <thinking>...</thinking>, and partial tags
    across chunk boundaries.
    """

    def __init__(self):
        self.thinking_parts: list[str] = []
        self.content_parts: list[str] = []
        self._in_thinking = False
        self._buffer = ""
        self._current_tag_name = ""

    def feed(self, chunk: str) -> tuple[str, str]:
        """Feed a new chunk and return (visible_content, thinking_so_far).

        Handles partial tags across chunk boundaries using a small buffer.
        """
        self._buffer += chunk

        while self._buffer:
            if self._in_thinking:
                end_idx = self._find_close_tag(self._buffer)
                if end_idx is not None:
                    tag_end = end_idx
                    self.thinking_parts.append(self._buffer[:tag_end])
                    self._buffer = self._buffer[tag_end:]
                    self._in_thinking = False
                elif self._might_have_partial_close(self._buffer):
                    break
                else:
                    self.thinking_parts.append(self._buffer)
                    self._buffer = ""
            else:
                open_idx = self._find_open_tag(self._buffer)
                if open_idx is not None:
                    tag_name, tag_start, tag_end = open_idx
                    self.content_parts.append(self._buffer[:tag_start])
                    self._buffer = self._buffer[tag_end:]
                    self._in_thinking = True
                    self._current_tag_name = tag_name
                elif self._might_have_partial_open(self._buffer):
                    safe_end = self._safe_flush_point(self._buffer)
                    if safe_end > 0:
                        self.content_parts.append(self._buffer[:safe_end])
                        self._buffer = self._buffer[safe_end:]
                    break
                else:
                    self.content_parts.append(self._buffer)
                    self._buffer = ""

        return "".join(self.content_parts), "".join(self.thinking_parts)

    def finalize(self) -> tuple[str, str]:
        """Flush remaining buffer (treat unclosed thinking as thinking content)."""
        if self._buffer:
            if self._in_thinking:
                self.thinking_parts.append(self._buffer)
            else:
                self.content_parts.append(self._buffer)
            self._buffer = ""
        return "".join(self.content_parts), "".join(self.thinking_parts)

    def _find_open_tag(self, text: str):
        """Find the first opening thinking tag. Returns (tag_name, start, end) or None."""
        tags = [("think", "<think>", "</think>"), ("thinking", "<thinking>", "</thinking>")]
        earliest = None
        for name, open_t, close_t in tags:
            idx = text.find(open_t)
            if idx != -1 and (earliest is None or idx < earliest[1]):
                earliest = (name, idx, idx + len(open_t))
        return earliest

    def _find_close_tag(self, text: str) -> int | None:
        """Find the first closing thinking tag. Returns end index or None."""
        if self._current_tag_name == "think":
            idx = text.find("</think>")
            if idx != -1:
                return idx + len("</think>")
        elif self._current_tag_name == "thinking":
            idx = text.find("</thinking>")
            if idx != -1:
                return idx + len("</thinking>")
        else:
            # Fallback: check both
            for close_t in ["</think>", "</thinking>"]:
                idx = text.find(close_t)
                if idx != -1:
                    return idx + len(close_t)
        return None

    def _might_have_partial_close(self, text: str) -> bool:
        """Check if buffer might contain a partial closing tag."""
        if self._current_tag_name == "think":
            return text.endswith("</think>") or len(text) < len("</think>") and "</think>".startswith(text)
        elif self._current_tag_name == "thinking":
            return text.endswith("</thinking>") or len(text) < len("</thinking>") and "</thinking>".startswith(text)
        return text.endswith("</think>") or text.endswith("</thinking>")

    def _might_have_partial_open(self, text: str) -> bool:
        """Check if buffer might contain a partial opening tag."""
        for open_t in ["<think>", "<thinking>"]:
            if text.endswith(open_t) or (len(text) < len(open_t) and open_t.startswith(text)):
                return True
        return False

    def _safe_flush_point(self, text: str) -> int:
        """Find a safe point to flush content before a potential partial tag."""
        for open_t in ["<think>", "<thinking>"]:
            if open_t.startswith(text):
                return 0
        return len(text)


# LLM tool definitions - names match the MCP server's tool names
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "searxng_search",
        "description": "Search the web for current information about a topic using SearXNG",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                }
            },
            "required": ["query"]
        }
    }
}

WEB_SCRAPE_TOOL = {
    "type": "function",
    "function": {
        "name": "web_scrape",
        "description": (
            "Scrape the full text content from a specific URL using Playwright. "
            "Use this to read articles, press releases, or any webpage in detail."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full URL to scrape (e.g., https://example.com/article)",
                    "pattern": "^https?://"
                }
            },
            "required": ["url"]
        }
    }
}

TOOLS = [WEB_SEARCH_TOOL, WEB_SCRAPE_TOOL]


class _MCPClient:
    """Singleton MCP client with a persistent stdio connection to the web-search MCP server.

    Starts the MCP server subprocess once in a background thread and keeps
    the session alive for the lifetime of the application. Tool calls are
    queued into the persistent event loop via asyncio.run_coroutine_threadsafe.

    Uses a dict sentinel (_state) instead of _instance to survive Streamlit's
    module re-execution — the class object persists in sys.modules so the
    dict reference is stable across reruns.
    """

    _state = {"_instance": None}

    @classmethod
    def get(cls) -> "_MCPClient":
        if cls._state["_instance"] is None:
            cls._state["_instance"] = cls()
        return cls._state["_instance"]

    def __init__(self):
        self._loop = None
        self._session = None
        self._stdio = None
        self._thread = None
        self._ready_event = threading.Event()
        self._started = False
        self._lock = threading.Lock()

        # Start the persistent server thread
        self._start_server()

    def _start_server(self):
        """Start the MCP server subprocess in a background thread."""
        def target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop

            try:
                server_params = StdioServerParameters(
                    command="bash",
                    args=[str(MCP_SERVER_DIR / "start.sh")],
                )

                async def _init():
                    stdio = stdio_client(server_params)
                    read, write = await stdio.__aenter__()
                    session = ClientSession(read, write)
                    await session.__aenter__()
                    await session.initialize()
                    return stdio, session

                self._stdio, self._session = loop.run_until_complete(_init())
                self._ready_event.set()
                logger.info("MCP server connected and ready.")

                # Keep the thread alive — run the loop until the process exits
                loop.run_forever()
            except Exception as e:
                logger.exception("MCP server initialization failed")
                self._ready_event.set()  # Unblock waiters so they can fail gracefully

        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()
        self._started = True

    @property
    def is_available(self) -> bool:
        """Check if the MCP server session is alive and responsive."""
        if self._session is None or self._loop is None:
            return False
        if self._thread is not None and not self._thread.is_alive():
            return False
        return True

    @classmethod
    def reset(cls):
        """Destroy the current instance and allow a fresh connection on next .get() call."""
        instance = cls._state.get("_instance")
        if instance is not None:
            # Stop the event loop if running
            if instance._loop is not None and instance._loop.is_running():
                instance._loop.call_soon_threadsafe(instance._loop.stop)
            # Wait for thread to finish
            if instance._thread is not None and instance._thread.is_alive():
                instance._thread.join(timeout=5)
        cls._state["_instance"] = None
        logger.info("MCP client reset — will reconnect on next use.")

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call an MCP tool synchronously using the persistent session.

        Blocks until the tool call completes (up to 30 seconds).
        """
        # Wait for the server to be ready (up to 10 seconds)
        if not self._ready_event.wait(timeout=10):
            return "MCP server failed to start."

        if not self.is_available:
            logger.warning("MCP server not available — attempting reconnection...")
            _MCPClient.reset()
            try:
                new_instance = _MCPClient()
                _MCPClient._state["_instance"] = new_instance
                if not new_instance._ready_event.wait(timeout=15):
                    return "MCP server reconnection timed out."
                if not new_instance.is_available:
                    return "MCP server reconnection failed."
                # Retry the tool call on the new instance
                return new_instance.call_tool(tool_name, arguments)
            except Exception as e:
                logger.exception("MCP server reconnection failed")
                return f"MCP server reconnection failed: {e}"

        # Submit the tool call to the persistent event loop
        async def _call():
            result = await self._session.call_tool(tool_name, arguments)
            return result

        # web_scrape (Playwright) needs more headroom than searxng_search
        timeout = 60 if tool_name == "web_scrape" else 30
        future = asyncio.run_coroutine_threadsafe(_call(), self._loop)
        try:
            result = future.result(timeout=timeout)
        except TimeoutError:
            logger.warning("MCP tool call timed out for %s (%ds)", tool_name, timeout)
            return f"MCP call timed out after {timeout}s. The remote service may be slow or unresponsive."
        except Exception as e:
            logger.exception("MCP tool call failed for %s", tool_name)
            return f"MCP call failed: {e}"

        texts = [
            c.text if hasattr(c, "text") else str(c)
            for c in result.content
            if hasattr(c, "type") and c.type == "text"
        ]
        return "\n".join(texts) if texts else "No content returned."


def _web_search(query: str) -> str:
    """Search the web via MCP server's searxng_search tool.

    Args:
        query: Search query string.

    Returns:
        Formatted search results text.
    """
    mcp = _MCPClient.get()
    return mcp.call_tool("searxng_search", {"query": query})


def _web_scrape(url: str) -> str:
    """Scrape a URL via MCP server's web_scrape tool (uses Playwright).

    Args:
        url: The URL to scrape.

    Returns:
        Text content from the page, truncated to MAX_SCRAPE_CONTENT_LENGTH.
    """
    mcp = _MCPClient.get()
    result = mcp.call_tool("web_scrape", {"url": url})
    if len(result) > MAX_SCRAPE_CONTENT_LENGTH:
        result = result[:MAX_SCRAPE_CONTENT_LENGTH] + "\n\n[Content truncated — showing first ~4000 characters]"
    return result


def _build_system_prompt(
    ticker: str,
    articles: Optional[list[dict]],
    summary: Optional[str],
) -> str:
    """Build system prompt based on available context.

    Args:
        ticker: Stock ticker symbol.
        articles: Scraped articles (optional).
        summary: Initial summary from summarizer (optional).

    Returns:
        System prompt string tailored to available context.
    """
    year_hint = SystemPrompts.YEAR_HINT.format(current_date=CURRENT_DATE)

    if articles and summary:
        articles_text = "\n".join(
            f"- {a.get('title', 'Untitled')} ({a.get('source', 'Unknown')}, {a.get('date', '')}) - URL: {a.get('url', 'N/A')}"
            for a in articles
        )
        return SystemPrompts.WITH_CONTEXT_TEMPLATE.format(
            ticker=ticker,
            summary=summary,
            articles_text=articles_text,
            year_hint=year_hint,
            citation_rule=SystemPrompts.CITATION_RULE,
            research_workflow=SystemPrompts.RESEARCH_WORKFLOW
        )
    else:
        return SystemPrompts.NO_CONTEXT_TEMPLATE.format(
            ticker=ticker,
            year_hint=year_hint,
            citation_rule=SystemPrompts.CITATION_RULE,
            research_workflow=SystemPrompts.RESEARCH_WORKFLOW
        )


def _execute_tool_call(tool_call) -> tuple[str, str]:
    """Execute an LLM tool call and return (tool_name, result_text).

    Handles searxng_search and web_scrape tool calls.

    Args:
        tool_call: The tool call object from the LLM response.

    Returns:
        Tuple of (tool_name, result_text).
    """
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)

    if name == "searxng_search":
        query = args.get("query", "").strip()
        if not query:
            return ("searxng_search", "Error: query parameter is required and cannot be empty.")
        return ("searxng_search", _web_search(query))
    elif name == "web_scrape":
        url = args.get("url", "").strip()
        if not url:
            return ("web_scrape", "Error: url parameter is required and cannot be empty.")
        return ("web_scrape", _web_scrape(url))
    else:
        return (name, f"Unknown tool: {name}")


def _run_tool_loop(
    question: str,
    ticker: str,
    history: list[dict],
    llm_url: str,
    model: str,
    articles: Optional[list[dict]] = None,
    summary: Optional[str] = None,
) -> dict:
    """Run the tool-calling loop synchronously.

    Executes LLM calls with tool calling until the model either:
    - Returns a text answer (no tool calls), or
    - Exceeds MAX_SEARCH_ITERATIONS

    Args:
        question: User's question.
        ticker: Stock ticker symbol.
        history: Prior chat messages [{role, content}, ...].
        llm_url: OpenAI-compatible LLM base URL.
        model: Model name.
        articles: Optional scraped articles for context.
        summary: Optional initial summary for context.

    Returns:
        Dict with:
        - 'messages': Full message list (for a follow-up streaming call if needed)
        - 'tool_calls': List of {tool, query/url, result} dicts for UI display
        - 'trimmed_history': Trimmed conversation history
        - 'answer': The text answer if the LLM returned one, or None
        - 'needs_final_call': True if the loop exhausted without a text answer
    """
    tool_calls_list = []
    search_count = 0

    client = OpenAI(base_url=llm_url, api_key="not-needed", timeout=120.0)
    system_prompt = _build_system_prompt(ticker, articles, summary)

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    trimmed_history = history[-(MAX_CHAT_TURNS * 2):] if len(history) > MAX_CHAT_TURNS * 2 else history
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": question})

    for iteration in range(MAX_SEARCH_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                temperature=TEMPERATURE,
                top_p=TOP_P,
                presence_penalty=PRESENCE_PENALTY,
                max_tokens=MAX_TOKENS,
                extra_body={
                    "top_k": 20,
                    "min_p": 0.00,
                },
            )
        except Exception as e:
            logger.exception("LLM call failed, falling back to text-only")
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=TEMPERATURE,
                    top_p=TOP_P,
                    presence_penalty=PRESENCE_PENALTY,
                    max_tokens=MAX_TOKENS,
                    extra_body={
                        "top_k": 20,
                        "min_p": 0.00,
                    },
                )
            except Exception as e2:
                return {
                    "messages": messages,
                    "tool_calls": tool_calls_list,
                    "trimmed_history": trimmed_history,
                    "answer": f"LLM error: {e2}",
                    "needs_final_call": False,
                }

        message = response.choices[0].message

        if message.tool_calls:
            tool_call_info = []

            # Accumulate thinking from this iteration
            cleaned_content, iteration_thinking = strip_thinking_tags(message.content or "")
            if iteration_thinking:
                if total_thinking:
                    total_thinking += "\n" + iteration_thinking
                else:
                    total_thinking = iteration_thinking

            assistant_msg = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in message.tool_calls
                ],
            }
            # Save cleaned content to history to prevent reasoning context poisoning
            if cleaned_content.strip():
                assistant_msg["content"] = cleaned_content.strip()
            messages.append(assistant_msg)

            # Execute tool calls (parallel where possible, with search limiting)
            turn_search_count = 0
            tool_results = {}  # tool_call.id -> (tool_name, result, args, blocked)

            # Separate searches (rate-limited) from scrapes (parallelizable)
            search_calls = [tc for tc in message.tool_calls if tc.function.name == "searxng_search"]
            other_calls = [tc for tc in message.tool_calls if tc.function.name != "searxng_search"]

            # Execute searches sequentially (to enforce limits)
            for tc in search_calls:
                args = json.loads(tc.function.arguments)
                turn_search_count += 1
                if turn_search_count > MAX_PARALLEL_SEARCHES:
                    tool_results[tc.id] = (
                        "searxng_search",
                        f"Parallel search limit reached ({MAX_PARALLEL_SEARCHES} per turn). "
                        "Process the results you already have — use web_scrape on the URLs found.",
                        args,
                        True,  # blocked
                    )
                elif search_count >= MAX_SEARCHES:
                    tool_results[tc.id] = (
                        "searxng_search",
                        f"Search limit reached ({MAX_SEARCHES}/{MAX_SEARCHES}). "
                        "STOP searching. Use web_scrape to read the full content of URLs from your previous "
                        "search results instead.",
                        args,
                        True,  # blocked
                    )
                else:
                    search_count += 1
                    tool_results[tc.id] = (
                        "searxng_search",
                        _web_search(args.get("query", "").strip()),
                        args,
                        False,
                    )

            # Execute scrapes and other tools in parallel
            if other_calls:
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_tc = {
                        executor.submit(_execute_tool_call, tc): tc
                        for tc in other_calls
                    }
                    for future in as_completed(future_to_tc):
                        tc = future_to_tc[future]
                        args = json.loads(tc.function.arguments)
                        try:
                            tool_name, result = future.result()
                        except Exception as e:
                            tool_name = tc.function.name
                            result = f"Tool execution failed: {e}"
                        tool_results[tc.id] = (tool_name, result, args, False)

            # Build tool call display info and append tool result messages (in original order)
            for tc in message.tool_calls:
                tool_name, result, args, blocked = tool_results[tc.id]

                if not blocked:
                    if tool_name == "searxng_search":
                        display = {
                            "tool": "searxng_search",
                            "query": args.get("query", ""),
                            "result": result,
                        }
                    elif tool_name == "web_scrape":
                        display = {
                            "tool": "web_scrape",
                            "url": args.get("url", ""),
                            "result": result,
                        }
                    else:
                        display = {"tool": tool_name, "result": result}
                    tool_call_info.append(display)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            tool_calls_list.extend(tool_call_info)
            continue

        # Text response — done
        raw_answer = message.content or ""
        answer, thinking = strip_thinking_tags(raw_answer)
        answer = _strip_tool_call_xml(answer)
        return {
            "messages": messages,
            "tool_calls": tool_calls_list,
            "trimmed_history": trimmed_history,
            "answer": answer,
            "thinking": thinking,
            "needs_final_call": False,
        }

    # Exceeded max iterations — need a final call to get the answer
    messages.append({
        "role": "system",
        "content": (
            "Please provide your final answer now based on the research results above. "
            "Do not make any more tool calls — just write your answer."
        ),
    })
    return {
        "messages": messages,
        "tool_calls": tool_calls_list,
        "trimmed_history": trimmed_history,
        "answer": None,
        "needs_final_call": True,
    }


def run_tool_loop_stream(
    question: str,
    ticker: str,
    history: list[dict],
    llm_url: str,
    model: str,
    articles: Optional[list[dict]] = None,
    summary: Optional[str] = None,
):
    """Streaming generator that yields events as the LLM researches and answers.

    Uses `stream=True` with the OpenAI client to provide real-time updates
    on content chunks, tool calls, and final results.

    Args:
        question: User's question.
        ticker: Stock ticker symbol.
        history: Prior chat messages [{role, content}, ...].
        llm_url: OpenAI-compatible LLM base URL.
        model: Model name.
        articles: Optional scraped articles for context.
        summary: Optional initial summary for context.

    Yields:
        Dict events with types:
        - {"type": "content_chunk", "chunk": delta_content, "full_content": accumulated,
           "cleaned_content": cleaned_accumulated, "current_thinking": thinking_so_far}
        - {"type": "tool_start", "tool": tool_name, "args": parsed_args_dict}
        - {"type": "tool_result", "tool": tool_name, "result": result_text}
        - {"type": "done", "messages": ..., "tool_calls": ..., "trimmed_history": ...,
           "answer": ..., "thinking": ..., "needs_final_call": ...}
        - {"type": "error", "error": error_message}
    """
    tool_calls_list = []
    search_count = 0

    client = OpenAI(base_url=llm_url, api_key="not-needed", timeout=120.0)
    system_prompt = _build_system_prompt(ticker, articles, summary)

    messages = [{"role": "system", "content": system_prompt}]

    trimmed_history = history[-(MAX_CHAT_TURNS * 2):] if len(history) > MAX_CHAT_TURNS * 2 else history
    # Only keep role and content for API compatibility, drop tool_calls/thinking metadata
    clean_history = [{"role": m["role"], "content": m["content"]} for m in trimmed_history]
    messages.extend(clean_history)
    messages.append({"role": "user", "content": question})

    total_thinking = ""

    for iteration in range(MAX_SEARCH_ITERATIONS):
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                temperature=TEMPERATURE,
                top_p=TOP_P,
                presence_penalty=PRESENCE_PENALTY,
                max_tokens=MAX_TOKENS,
                extra_body={
                    "top_k": 20,
                    "min_p": 0.00,
                },
                stream=True,
            )
        except Exception as e:
            logger.exception("LLM call failed")
            yield {"type": "error", "error": str(e)}
            return

        current_content = ""
        current_tool_calls = []

        # Per-iteration streaming parser for efficient thinking/content separation
        parser = StreamingThinkingParser()

        # Consume the streaming response
        is_thinking = False
        for chunk in stream:
            delta = chunk.choices[0].delta

            # Support vLLM/OpenRouter reasoning_content natively
            r_content = getattr(delta, "reasoning_content", None)
            if not r_content and hasattr(delta, "model_extra") and delta.model_extra:
                r_content = delta.model_extra.get("reasoning_content")

            content_to_add = ""
            if r_content:
                if not is_thinking:
                    content_to_add += "<think>\n"
                    is_thinking = True
                content_to_add += r_content

            if delta.content:
                if is_thinking:
                    content_to_add += "\n</think>\n"
                    is_thinking = False
                content_to_add += delta.content

            if content_to_add:
                current_content += content_to_add
                cleaned_content, current_thinking = parser.feed(content_to_add)
                yield {
                    "type": "content_chunk",
                    "chunk": content_to_add,
                    "full_content": current_content,
                    "cleaned_content": cleaned_content,
                    "current_thinking": current_thinking,
                }
                
            if delta.tool_calls:
                for tc_chunk in delta.tool_calls:
                    while len(current_tool_calls) <= tc_chunk.index:
                        current_tool_calls.append({
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""}
                        })
                    tc = current_tool_calls[tc_chunk.index]
                    if tc_chunk.id:
                        tc["id"] += tc_chunk.id
                    if tc_chunk.function.name:
                        tc["function"]["name"] += tc_chunk.function.name
                    if tc_chunk.function.arguments:
                        tc["function"]["arguments"] += tc_chunk.function.arguments

        if is_thinking:
            current_content += "\n</think>\n"

        # Finalize the parser for this iteration
        cleaned_content, iteration_thinking = parser.finalize()

        # If tool calls detected, execute them and loop back
        if current_tool_calls:
            # Accumulate thinking from this iteration before resetting current_content
            if iteration_thinking:
                if total_thinking:
                    total_thinking += "\n" + iteration_thinking
                else:
                    total_thinking = iteration_thinking
            assistant_msg = {
                "role": "assistant",
                "tool_calls": current_tool_calls,
            }
            # Save cleaned content to history to prevent reasoning context poisoning
            if cleaned_content.strip():
                assistant_msg["content"] = cleaned_content.strip()
            messages.append(assistant_msg)

            # Separate searches (rate-limited) from scrapes (parallelizable)
            search_calls = [tc for tc in current_tool_calls if tc["function"]["name"] == "searxng_search"]
            other_calls = [tc for tc in current_tool_calls if tc["function"]["name"] != "searxng_search"]

            turn_search_count = 0
            tool_results = {}  # tc_id -> (tool_name, result, args, blocked)

            # Execute searches sequentially (to enforce limits)
            for tc in search_calls:
                args = json.loads(tc["function"]["arguments"])
                turn_search_count += 1
                if turn_search_count > MAX_PARALLEL_SEARCHES:
                    tool_results[tc["id"]] = (
                        "searxng_search",
                        f"Parallel search limit reached ({MAX_PARALLEL_SEARCHES} per turn). "
                        "Process the results you already have — use web_scrape on the URLs found.",
                        args,
                        True,  # blocked
                    )
                elif search_count >= MAX_SEARCHES:
                    tool_results[tc["id"]] = (
                        "searxng_search",
                        f"Search limit reached ({MAX_SEARCHES}/{MAX_SEARCHES}). "
                        "STOP searching. Use web_scrape to read the full content of URLs from your previous "
                        "search results instead.",
                        args,
                        True,  # blocked
                    )
                else:
                    search_count += 1
                    yield {"type": "tool_start", "tool": "searxng_search", "args": args}
                    result = _web_search(args.get("query", "").strip())
                    yield {"type": "tool_result", "tool": "searxng_search", "result": result}
                    tool_results[tc["id"]] = ("searxng_search", result, args, False)

            # Execute scrapes and other tools in parallel
            if other_calls:
                for tc in other_calls:
                    args = json.loads(tc["function"]["arguments"])
                    yield {"type": "tool_start", "tool": tc["function"]["name"], "args": args}

                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_tc = {
                        executor.submit(
                            _execute_tool_call,
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name=tc["function"]["name"],
                                    arguments=tc["function"]["arguments"],
                                )
                            ),
                        ): tc
                        for tc in other_calls
                    }
                    for future in as_completed(future_to_tc):
                        tc = future_to_tc[future]
                        args = json.loads(tc["function"]["arguments"])
                        try:
                            tool_name, result = future.result()
                        except Exception as e:
                            tool_name = tc["function"]["name"]
                            result = f"Tool execution failed: {e}"
                        yield {"type": "tool_result", "tool": tool_name, "result": result}
                        tool_results[tc["id"]] = (tool_name, result, args, False)

            # Build tool call display info and append tool result messages (in original order)
            for tc in current_tool_calls:
                tool_name, result, args, blocked = tool_results[tc["id"]]

                if not blocked:
                    if tool_name == "searxng_search":
                        display = {
                            "tool": "searxng_search",
                            "query": args.get("query", ""),
                            "result": result,
                        }
                    elif tool_name == "web_scrape":
                        display = {
                            "tool": "web_scrape",
                            "url": args.get("url", ""),
                            "result": result,
                        }
                    else:
                        display = {"tool": tool_name, "result": result}
                    tool_calls_list.append(display)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            continue

        # Text response — done
        # Use parser's finalized output (already computed above)
        cleaned = _strip_tool_call_xml(cleaned_content)
        # Combine thinking from all iterations
        full_thinking = total_thinking + ("\n" + iteration_thinking if total_thinking and iteration_thinking else "")
        full_thinking = full_thinking or iteration_thinking
        yield {
            "type": "done",
            "messages": messages,
            "tool_calls": tool_calls_list,
            "trimmed_history": trimmed_history,
            "answer": cleaned,
            "thinking": full_thinking,
            "total_thinking": full_thinking,
            "needs_final_call": False,
        }
        return

    # Exceeded max iterations — need a final call to get the answer
    messages.append({
        "role": "system",
        "content": (
            "Please provide your final answer now based on the research results above. "
            "Do not make any more tool calls — just write your answer."
        ),
    })
    yield {
        "type": "done",
        "messages": messages,
        "tool_calls": tool_calls_list,
        "trimmed_history": trimmed_history,
        "answer": None,
        "thinking": total_thinking,
        "total_thinking": total_thinking,
        "needs_final_call": True,
    }


def stream_final_answer(messages: list[dict], llm_url: str, model: str):
    """Generator that yields text chunks from a streaming LLM call.

    Used after _run_tool_loop when the loop exhausted its iterations and
    needs a final answer from the LLM.

    Args:
        messages: Full message history (including system prompt + tool results).
        llm_url: OpenAI-compatible LLM base URL.
        model: Model name.

    Yields:
        Text chunks (strings) as they arrive from the LLM.
    """
    client = OpenAI(base_url=llm_url, api_key="not-needed", timeout=120.0)
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            presence_penalty=PRESENCE_PENALTY,
            extra_body={
                "top_k": 20,
                "min_p": 0.00,
            },
            stream=True,
        )
        is_thinking = False
        for chunk in stream:
            delta = chunk.choices[0].delta
            
            r_content = getattr(delta, "reasoning_content", None)
            if not r_content and hasattr(delta, "model_extra") and delta.model_extra:
                r_content = delta.model_extra.get("reasoning_content")
                
            if r_content:
                if not is_thinking:
                    yield "<think>\n"
                    is_thinking = True
                yield r_content
                
            if delta.content:
                if is_thinking:
                    yield "\n</think>\n"
                    is_thinking = False
                yield delta.content
                
        if is_thinking:
            yield "\n</think>\n"
    except Exception as e:
        logger.exception("Streaming LLM call failed")
        yield f"LLM error: {e}"


def ask_followup(
    question: str,
    ticker: str,
    history: list[dict],
    llm_url: str,
    model: str,
    articles: Optional[list[dict]] = None,
    summary: Optional[str] = None,
) -> dict:
    """Process a follow-up question with multi-turn chat and MCP tool calling.

    Backward-compatible synchronous wrapper around _run_tool_loop + stream_final_answer.

    Args:
        question: User's question.
        ticker: Stock ticker symbol.
        history: Prior chat messages [{role, content}, ...].
        llm_url: OpenAI-compatible LLM base URL.
        model: Model name.
        articles: Optional scraped articles for context.
        summary: Optional initial summary for context.

    Returns:
        Dict with 'answer' (LLM response text), 'history' (updated message list),
        and 'tool_calls' (list of {tool, query, result} dicts for UI display).
    """
    if not question.strip():
        return {"answer": "", "history": history, "tool_calls": []}

    result = _run_tool_loop(question, ticker, history, llm_url, model, articles, summary)

    if result["needs_final_call"]:
        # Collect streaming chunks into a single string
        chunks = list(stream_final_answer(result["messages"], llm_url, model))
        raw_answer = "".join(chunks)
        answer, _ = strip_thinking_tags(raw_answer)
        answer = _strip_tool_call_xml(answer)
        if not answer:
            answer = "Search limit reached. I'll provide my best answer with the information I have."
    else:
        answer = result["answer"]

    trimmed = result["trimmed_history"]
    new_history = trimmed + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]
    return {"answer": answer, "history": new_history, "tool_calls": result["tool_calls"]}


def warm_mcp():
    """Pre-initialize the MCP server connection.

    Call this at app startup to avoid cold-start delay on the first chat question.
    Non-blocking — the server starts in a background thread.
    """
    try:
        _MCPClient.get()
        logger.info("MCP server warm-start initiated.")
    except Exception:
        logger.warning("MCP server warm-start failed — will retry on first use.")



