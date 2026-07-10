"""Summarize stock news articles using a local LLM."""

from typing import Dict

from openai import OpenAI


SYSTEM_PROMPT = """You are a financial news analyst. Given a list of news articles about a stock, provide a concise summary covering:

1. **Key Themes** — What are the main topics trending in the news?
2. **Bullish/Bearish Signals** — Are the overall signals positive, negative, or mixed?
3. **Notable Events** — Any specific events, earnings, or announcements worth highlighting.

Keep the summary under 300 words. Use markdown formatting."""


def summarize_news(articles: list[dict], llm_url: str, model: str) -> Dict[str, str]:
    """Send articles to a local LLM and return a dict with 'summary' and 'thinking'.

    Args:
        articles: List of dicts with keys: title, source, date, url, snippet.
        llm_url: Base URL of the OpenAI-compatible chat completions endpoint.
        model: Model name to use.

    Returns:
        Dict with 'summary' (clean markdown) and 'thinking' (chain-of-thought text, if any).
    """
    client = OpenAI(base_url=llm_url, api_key="not-needed")

    articles_text = "\n\n".join(
        f"**{a.get('title', 'Untitled')}** ({a.get('source', 'Unknown')}, {a.get('date', '')})\n{a.get('snippet', '')}"
        for a in articles
    )

    user_prompt = f"Summarize the following news articles:\n\n{articles_text}"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )

    content = response.choices[0].message.content or ""

    from chat import strip_thinking_tags
    summary, thinking = strip_thinking_tags(content)

    return {
        "summary": summary.strip(),
        "thinking": thinking,
    }
