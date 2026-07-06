"""Multi-turn chat with MCP-based web search and scrape for stock news analysis."""

import asyncio
import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from openai import OpenAI

logger = logging.getLogger(__name__)

CURRENT_YEAR = datetime.now().year


def _strip_tool_call_xml(text: str) -> str:
    """Strip raw tool call XML (\u2458function=...\u2459) from LLM content.

    Some LLMs include the raw function-calling syntax in the content field
    alongside structured tool_calls. This strips those artifacts.
    """
    # Match <tool_call><function=name> ... </function></tool_call> patterns
    text = re.sub(r'\u2458\s*<function=[^>]*>.*?</function>\s*\u2459', '', text, flags=re.DOTALL)
    # Match <tool_call><function=name> <parameter=...> ... </parameter> </function></tool_call> (inline)
    text = re.sub(r'\u2458\s*<function=[^>]*>\s*<parameter=[^>]*>.*?</function>\s*\u2459', '', text, flags=re.DOTALL)
    # Match unclosed <tool_call><function=... patterns
    text = re.sub(r'\u2458\s*<function=[^>]*>.*$', '', text, flags=re.DOTALL | re.MULTILINE)
    return text.strip()

MCP_SERVER_DIR = Path.home() / "Projects" / "web-search-MCP"
MAX_SEARCH_ITERATIONS = 5
MAX_CHAT_TURNS = 10

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
                    command="uv",
                    args=["--directory", str(MCP_SERVER_DIR), "run", "web-search-mcp"],
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

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call an MCP tool synchronously using the persistent session.

        Blocks until the tool call completes (up to 30 seconds).
        """
        # Wait for the server to be ready (up to 10 seconds)
        if not self._ready_event.wait(timeout=10):
            return "MCP server failed to start."

        if not self.is_available:
            return "MCP server is not available."

        # Submit the tool call to the persistent event loop
        async def _call():
            result = await self._session.call_tool(tool_name, arguments)
            return result

        future = asyncio.run_coroutine_threadsafe(_call(), self._loop)
        try:
            result = future.result(timeout=30)
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
        Text content from the page.
    """
    mcp = _MCPClient.get()
    return mcp.call_tool("web_scrape", {"url": url})


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
    year_hint = f"Today's year is {CURRENT_YEAR}. When searching for upcoming events, earnings, or catalysts, " \
                f"use queries that target {CURRENT_YEAR} and {CURRENT_YEAR + 1}."
    tool_instructions = (
        "\n\nRESEARCH WORKFLOW (follow these steps):\n"
        "1. Use searxng_search to find relevant URLs for the user's question.\n"
        "2. From the search results, identify the most relevant URLs (articles, forum posts, press releases).\n"
        "3. Use web_scrape to read the full content of those URLs — do NOT skip this step.\n"
        "4. Synthesize your answer from the scraped content, not just from search snippets.\n\n"
        "IMPORTANT: Search results only contain short snippets. You MUST use web_scrape on promising URLs "
        "to get the full article content before forming your answer. Never answer based solely on search "
        "snippets — always scrape at least 2-3 relevant pages."
    )
    if articles and summary:
        articles_text = "\n".join(
            f"- {a.get('title', 'Untitled')} ({a.get('source', 'Unknown')}, {a.get('date', '')})"
            for a in articles
        )
        return (
            f"You are a financial news analyst helping a user understand news about {ticker}.\n"
            f"You have access to the following context:\n\n"
            f"INITIAL SUMMARY:\n{summary}\n\n"
            f"ARTICLES:\n{articles_text}\n\n"
            f"{year_hint}\n\n"
            f"Answer the user's question based on this context. "
            f"If you need additional current information, follow the research workflow below.\n"
            f"Be concise and cite sources when referencing specific claims."
            f"{tool_instructions}"
        )
    else:
        return (
            f"You are a financial news analyst helping a user research {ticker}.\n"
            f"{year_hint}\n\n"
            f"Follow the research workflow below to answer the user's question.\n"
            f"Be concise and cite sources when referencing specific claims."
            f"{tool_instructions}"
        )


def _execute_tool_call(tool_call) -> tuple[str, str]:
    """Execute an LLM tool call and return (tool_name, result_text).

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

    # Reset tool calls tracking for this invocation
    ask_followup._tool_calls = []

    client = OpenAI(base_url=llm_url, api_key="not-needed", timeout=120.0)
    system_prompt = _build_system_prompt(ticker, articles, summary)

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # Trim history to last MAX_CHAT_TURNS turns if needed
    trimmed_history = history[-(MAX_CHAT_TURNS * 2):] if len(history) > MAX_CHAT_TURNS * 2 else history
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": question})

    # Tool-calling loop (max MAX_SEARCH_ITERATIONS iterations)
    for _ in range(MAX_SEARCH_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                temperature=0.1,
            )
        except Exception as e:
            logger.exception("LLM call failed, falling back to text-only")
            # Retry without tools
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.1,
                )
            except Exception as e2:
                error_answer = f"LLM error: {e2}"
                new_history = trimmed_history + [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": error_answer},
                ]
                return {"answer": error_answer, "history": new_history, "tool_calls": ask_followup._tool_calls}

        message = response.choices[0].message

        if message.tool_calls:
            # Collect tool call metadata for UI display
            tool_call_info = []

            # Append assistant's tool call message FIRST (API expects: assistant -> tool results)
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
            if message.content:
                assistant_msg["content"] = message.content
            messages.append(assistant_msg)

            # Then append tool results
            for tool_call in message.tool_calls:
                tool_name, result = _execute_tool_call(tool_call)

                # Build display info based on tool type
                args = json.loads(tool_call.function.arguments)
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
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

            # Store tool call info for this iteration
            if not hasattr(ask_followup, "_tool_calls"):
                ask_followup._tool_calls = []
            ask_followup._tool_calls.extend(tool_call_info)
            continue  # Loop back to call LLM again with tool results

        # Text response - done
        answer = message.content or ""
        new_history = trimmed_history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
        return {
            "answer": answer,
            "history": new_history,
            "tool_calls": ask_followup._tool_calls,
        }

    # Exceeded max iterations - call LLM one final time with accumulated context (no tools)
    try:
        final_response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
        )
        answer = final_response.choices[0].message.content or "Search limit reached."
    except Exception:
        answer = "Search limit reached. I'll provide my best answer with the information I have."

    new_history = trimmed_history + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]
    return {
        "answer": answer,
        "history": new_history,
        "tool_calls": ask_followup._tool_calls,
    }


def ask_followup_stream(
    question: str,
    ticker: str,
    history: list[dict],
    llm_url: str,
    model: str,
    articles: Optional[list[dict]] = None,
    summary: Optional[str] = None,
) -> dict:
    """Process a follow-up question with streaming LLM response.

    Uses non-streaming calls for tool-call iterations (reliable, no buffer
    issues), then attempts a streaming call for the final text response.
    Falls back to non-streaming if streaming fails.

    Args:
        question: User's question.
        ticker: Stock ticker symbol.
        history: Prior chat messages [{role, content}, ...].
        llm_url: OpenAI-compatible LLM base URL.
        model: Model name.
        articles: Optional scraped articles for context.
        summary: Optional initial summary for context.

    Returns:
        Dict with 'stream' (generator yielding text chunks),
        'tool_calls' (list of {tool, query, result} dicts),
        and 'error' (set if an error occurred).
    """
    if not question.strip():
        def empty_gen():
            return iter([])
        return {"stream": empty_gen(), "tool_calls": [], "error": None}

    # Reset tool calls tracking
    ask_followup_stream._tool_calls = []
    ask_followup_stream._error = None

    client = OpenAI(base_url=llm_url, api_key="not-needed", timeout=120.0)
    system_prompt = _build_system_prompt(ticker, articles, summary)

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # Trim history to last MAX_CHAT_TURNS turns if needed
    trimmed_history = history[-(MAX_CHAT_TURNS * 2):] if len(history) > MAX_CHAT_TURNS * 2 else history
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": question})

    # Tool-calling loop — use non-streaming for reliability
    for _ in range(MAX_SEARCH_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                temperature=0.1,
            )
        except Exception as e:
            logger.exception("LLM call failed")
            error_msg = f"LLM error: {e}"
            def error_gen(msg=error_msg):
                yield msg
            ask_followup_stream._error = error_msg
            return {"stream": error_gen(), "tool_calls": ask_followup_stream._tool_calls, "error": error_msg}

        message = response.choices[0].message

        if message.tool_calls:
            # Tool call — append assistant message, execute tools, loop back
            tool_call_info = []

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
            if message.content:
                assistant_msg["content"] = message.content
            messages.append(assistant_msg)

            for tool_call in message.tool_calls:
                tool_name, result = _execute_tool_call(tool_call)
                args = json.loads(tool_call.function.arguments)
                display = {
                    "tool": tool_name,
                    "query": args.get("query", ""),
                    "url": args.get("url", ""),
                    "result": result,
                }
                tool_call_info.append(display)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

            ask_followup_stream._tool_calls.extend(tool_call_info)
            continue  # Loop back with tool results

        # Text response — we already have the content from the non-streaming call.
        # Simulate word-by-word streaming from it (reliable, no connection issues).
        content = _strip_tool_call_xml(message.content or "")

        def text_stream(text=content):
            """Simulate word-by-word streaming from buffered content."""
            for word in text.split():
                yield word + " "

        return {
            "stream": text_stream(),
            "tool_calls": ask_followup_stream._tool_calls,
            "error": None,
        }

    # Exceeded max iterations — final non-streaming call without tools
    try:
        final_response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
        )
        answer = _strip_tool_call_xml(final_response.choices[0].message.content or "Search limit reached.")
    except Exception as e:
        answer = f"Search limit reached. LLM error: {e}"

    def final_gen(text=answer):
        for word in text.split():
            yield word + " "

    return {
        "stream": final_gen(),
        "tool_calls": ask_followup_stream._tool_calls,
        "error": None,
    }
