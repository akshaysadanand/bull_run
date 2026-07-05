"""Multi-turn chat with web search tool calling for stock news analysis."""

import json
import logging
from typing import Optional
from urllib.parse import quote_plus
from urllib.request import urlopen

logger = logging.getLogger(__name__)

SEARXNG_URL = "http://localhost:8088"
MAX_SEARCH_ITERATIONS = 3
MAX_CHAT_TURNS = 10


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
