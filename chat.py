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
    """Strip raw tool call XML (`<tool_call>...</tool_call>`) from LLM content.

    Some LLMs include the raw function-calling syntax in the content field
    alongside structured tool_calls. This strips those artifacts.

    Matches ANY content between the sentinel characters `<tool_call>` (U+2458) and
    `</tool_call>` (U+2459), regardless of internal XML structure.
    """
    # Match anything between sentinels: `<tool_call> ... _` (handles newlines, malformed XML, etc.)
    text = re.sub(r'\u2458.*?\u2459', '', text, flags=re.DOTALL)
    # Match unclosed `<tool_call>` — strip everything from sentinel to end of string
    text = re.sub(r'\u2458.*$', '', text, flags=re.DOTALL | re.MULTILINE)
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
    # Extract thinking content
    thinking_parts = re.findall(r'<think>(.*?)</think>', text, flags=re.DOTALL | re.IGNORECASE)
    thinking_parts += re.findall(r'<thinking>(.*?)</thinking>', text, flags=re.DOTALL | re.IGNORECASE)
    # Catch trailing incomplete thinking fragments
    thinking_parts += re.findall(r'<think>(.*?)$', text, flags=re.DOTALL | re.IGNORECASE)

    thinking = "\n".join(p.strip() for p in thinking_parts if p.strip())

    # Strip all thinking blocks from the text
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<thinking>.*?</thinking>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'\s*<think>.*$', '', cleaned, flags=re.DOTALL | re.IGNORECASE)

    return cleaned.strip(), thinking


MCP_SERVER_DIR = Path.home() / "Projects" / "web-search-MCP"
MAX_SEARCH_ITERATIONS = 3
MAX_CHAT_TURNS = 10
MAX_SEARCHES = 3  # Hard cap on searxng_search calls per question
MAX_PARALLEL_SEARCHES = 2  # Max searxng_search calls the LLM can make in a single turn
MAX_SCRAPE_CONTENT_LENGTH = 4000  # Truncate scraped page content to limit context size

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
    year_hint = f"Today's year is {CURRENT_YEAR}. When searching for upcoming events, earnings, or catalysts, " \
                f"use queries that target {CURRENT_YEAR} and {CURRENT_YEAR + 1}."
    tool_instructions = (
        "\n\nRESEARCH WORKFLOW (strict — follow in order):\n"
        "1. Do 1-2 searxng_search calls to find relevant URLs. Maximum 2 parallel searches per turn, 3 total.\n"
        "2. Use web_scrape on 2-3 of the most relevant URLs from your search results.\n"
        "3. Synthesize your answer from the scraped content, not from search snippets.\n\n"
        "CRITICAL RULES:\n"
        "- Search results only contain short snippets with URLs. You MUST use web_scrape to read full content.\n"
        "- Never answer based solely on search snippets — always scrape at least 2-3 relevant pages first.\n"
        "- After 2 searches, STOP searching and start scraping the URLs you found.\n"
        "- Do NOT issue more than 3 searxng_search calls total. After that, only use web_scrape.\n"
        "- For simple factual queries (prices, dates, tickers), 1 search is enough — don't over-search."
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
            f"Always cite the sources you used to form your answer, and include the URL of each source in your response."
            f"{tool_instructions}"
        )


def _execute_tool_call(tool_call, search_count: list[int]) -> tuple[str, str]:
    """Execute an LLM tool call and return (tool_name, result_text).

    Args:
        tool_call: The tool call object from the LLM response.
        search_count: Mutable list with single int tracking total searches (allows mutation in closure).

    Returns:
        Tuple of (tool_name, result_text).
    """
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)

    if name == "searxng_search":
        query = args.get("query", "").strip()
        if not query:
            return ("searxng_search", "Error: query parameter is required and cannot be empty.")
        search_count[0] += 1
        if search_count[0] > MAX_SEARCHES:
            return (
                "searxng_search",
                f"Search limit reached ({MAX_SEARCHES}/{MAX_SEARCHES}). "
                "STOP searching. Use web_scrape to read the full content of URLs from your previous "
                "search results instead. Do not issue any more searxng_search calls."
            )
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

    # Track search count to enforce MAX_SEARCHES limit
    search_count = [0]
    searches_done = [False]  # After first iteration with searches, block further searches

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
    for iteration in range(MAX_SEARCH_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                temperature=0.1,
                max_tokens=4096,
            )
        except Exception as e:
            logger.exception("LLM call failed, falling back to text-only")
            # Retry without tools
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=4096,
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

            # Then append tool results (enforce per-turn parallel search limit)
            turn_search_count = [0]
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                # Enforce per-turn parallel search limit
                blocked = False
                if name == "searxng_search":
                    turn_search_count[0] += 1
                    if searches_done[0]:
                        # After the first iteration, block all further searches
                        tool_name = "searxng_search"
                        result = (
                            "Searches are now closed. You have search results with URLs. "
                            "Use web_scrape to read the full content of the most relevant URLs, "
                            "or synthesize your answer from what you already have."
                        )
                        blocked = True
                    elif turn_search_count[0] > MAX_PARALLEL_SEARCHES:
                        tool_name = "searxng_search"
                        result = (
                            f"Parallel search limit reached ({MAX_PARALLEL_SEARCHES} per turn). "
                            "Process the results you already have — use web_scrape on the URLs found."
                        )
                        blocked = True
                    elif search_count[0] >= MAX_SEARCHES:
                        tool_name = "searxng_search"
                        result = (
                            f"Search limit reached ({MAX_SEARCHES}/{MAX_SEARCHES}). "
                            "STOP searching. Use web_scrape to read the full content of URLs from your previous "
                            "search results instead. Do not issue any more searxng_search calls."
                        )
                        blocked = True
                    else:
                        search_count[0] += 1
                        tool_name, result = ("searxng_search", _web_search(args.get("query", "").strip()))
                else:
                    tool_name, result = _execute_tool_call(tool_call, search_count)

                # Build display info based on tool type (skip blocked calls from UI)
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
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

            # Store tool call info for this iteration
            if not hasattr(ask_followup, "_tool_calls"):
                ask_followup._tool_calls = []
            ask_followup._tool_calls.extend(tool_call_info)

            # After the first iteration with searches, lock searches so subsequent
            # iterations can only scrape or answer.
            if search_count[0] > 0:
                searches_done[0] = True

            # Enforce search -> scrape pattern: if this iteration was all searches and we've
            # already done searches before, inject a corrective reminder forcing web_scrape.
            tool_names_this_iter = [d["tool"] for d in tool_call_info]
            if (
                all(t == "searxng_search" for t in tool_names_this_iter)
                and search_count[0] >= 2
            ):
                reminder = (
                    "\u26a0 REMINDER: You already have search results with URLs. "
                    "STOP searching and use web_scrape to read the full content of at least "
                    "2-3 of the most relevant URLs from your search results. "
                    "Do not issue any more searxng_search calls until you have scraped content."
                )
                messages.append({
                    "role": "user",
                    "content": reminder,
                })

            continue  # Loop back to call LLM again with tool results

        # Text response - done
        raw_answer = message.content or ""
        answer, _ = strip_thinking_tags(raw_answer)
        answer = _strip_tool_call_xml(answer)
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
    # Add a final instruction to force a text response
    messages.append({
        "role": "user",
        "content": (
            "Please provide your final answer now based on the research results above. "
            "Do not make any more tool calls — just write your answer."
        ),
    })
    try:
        final_response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=4096,
        )
        raw_answer = final_response.choices[0].message.content or "Search limit reached."
        answer, _ = strip_thinking_tags(raw_answer)
        answer = _strip_tool_call_xml(answer)
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



