"""Multi-turn chat with web search tool calling for stock news analysis."""

import json
import logging
from typing import Optional
from urllib.parse import quote_plus
from urllib.request import urlopen

from openai import OpenAI

logger = logging.getLogger(__name__)

SEARXNG_URL = "http://localhost:8088"
MAX_SEARCH_ITERATIONS = 3
MAX_CHAT_TURNS = 10

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information about a topic",
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
            f"Answer the user's question based on this context. "
            f"If you need additional current information, use the web_search tool. "
            f"Be concise and cite sources when referencing specific claims."
        )
    else:
        return (
            f"You are a financial news analyst helping a user research {ticker}.\n"
            f"Use the web_search tool to find current information. "
            f"Be concise and cite sources when referencing specific claims."
        )


def _web_search(query: str) -> str:
    """Search the web via SearXNG and return formatted text results.

    Args:
        query: Search query string.

    Returns:
        Formatted text with titles, URLs, and snippets from top results.
        Empty string on failure.
    """
    url = f"{SEARXNG_URL}/search?q={quote_plus(query)}&format=json"
    try:
        with urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())

    except Exception as e:
        logger.exception("Web search failed for query: %s", query)
        return f"Search failed: {e}"

    results = data.get("results", [])
    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results[:5], 1):
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        content = r.get("content", "")
        lines.append(f"[{i}] {title}")
        if url:
            lines.append(f"    URL: {url}")
        if content:
            snippet = content[:300]
            if len(content) > 300:
                snippet += "..."
            lines.append(f"    {snippet}")
        lines.append("")

    return "\n".join(lines)


def ask_followup(
    question: str,
    ticker: str,
    history: list[dict],
    llm_url: str,
    model: str,
    articles: Optional[list[dict]] = None,
    summary: Optional[str] = None,
) -> dict:
    """Process a follow-up question with multi-turn chat and web search tool calling.

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

    client = OpenAI(base_url=llm_url, api_key="not-needed")

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
                tools=[WEB_SEARCH_TOOL],
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
            messages.append({
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
            })

            # Then append tool results
            for tool_call in message.tool_calls:
                if tool_call.function.name == "web_search":
                    args = json.loads(tool_call.function.arguments)
                    query = args.get("query", "")
                    search_result = _web_search(query)

                    tool_call_info.append({
                        "tool": "web_search",
                        "query": query,
                        "result": search_result,
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": search_result,
                    })

            # Store tool call info for this iteration
            if not hasattr(ask_followup, "_tool_calls"):
                ask_followup._tool_calls = []
            ask_followup._tool_calls.extend(tool_call_info)
            continue  # Loop back to call LLM again with tool results

        # Text response — done
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

    # Exceeded max iterations — call LLM one final time with accumulated context (no tools)
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

    Runs the tool-calling loop synchronously, then streams the final LLM
    response token-by-token. Returns a dict with 'tool_calls' (populated
    as searches run) and 'stream' (a generator yielding text chunks).

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

    client = OpenAI(base_url=llm_url, api_key="not-needed")
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
                tools=[WEB_SEARCH_TOOL],
                temperature=0.1,
            )
        except Exception as e:
            logger.exception("LLM call failed, falling back to text-only")
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.1,
                )
            except Exception as e2:
                def error_gen():
                    yield f"LLM error: {e2}"
                ask_followup_stream._error = str(e2)
                return {"stream": error_gen(), "tool_calls": ask_followup_stream._tool_calls, "error": str(e2)}

        message = response.choices[0].message

        if message.tool_calls:
            tool_call_info = []
            messages.append({
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
            })

            for tool_call in message.tool_calls:
                if tool_call.function.name == "web_search":
                    args = json.loads(tool_call.function.arguments)
                    query = args.get("query", "")
                    search_result = _web_search(query)
                    tool_call_info.append({
                        "tool": "web_search",
                        "query": query,
                        "result": search_result,
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": search_result,
                    })

            ask_followup_stream._tool_calls.extend(tool_call_info)
            continue

        # Text response (no tool calls) — stream a new call with same messages
        break  # Exit loop, fall through to streaming final call

    # Stream final LLM call and extract thinking tags
    import re

    def final_stream():
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                stream=True,
            )
            full_text = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_text += delta
                    yield delta
            # Extract thinking after streaming completes
            thinking_parts = re.findall(r'<think>(.*?)</think>', full_text, flags=re.DOTALL | re.IGNORECASE)
            thinking_parts += re.findall(r'<thinking>(.*?)</thinking>', full_text, flags=re.DOTALL | re.IGNORECASE)
            ask_followup_stream._thinking = "\n".join(p.strip() for p in thinking_parts if p.strip())
        except Exception as e:
            logger.exception("Streaming failed")
            yield f"Streaming error: {e}"

    return {
        "stream": final_stream(),
        "tool_calls": ask_followup_stream._tool_calls,
        "error": None,
    }
