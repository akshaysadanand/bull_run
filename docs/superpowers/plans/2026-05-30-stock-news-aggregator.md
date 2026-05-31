# Stock News Aggregator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Streamlit app that scrapes stock news from Yahoo Finance via Playwright and summarizes it with a local LLM.

**Architecture:** Three modules — `scraper.py` (Playwright headless browser), `summarizer.py` (OpenAI-compatible LLM client), `app.py` (Streamlit UI) — each with a single public function and clear boundaries.

**Tech Stack:** Python 3.11+, uv, Streamlit, Playwright, openai SDK, pytest

---

## File Structure

```
bull_run/
├── pyproject.toml
├── scraper.py          # scrape_news(ticker) -> list[dict]
├── summarizer.py       # summarize_news(articles, llm_url, model) -> str
├── app.py              # Streamlit UI
├── tests/
│   ├── test_scraper.py
│   └── test_summarizer.py
└── docs/
    └── superpowers/
        ├── specs/
        └── plans/
```

---

### Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Create pyproject.toml with project metadata and dependencies**

```toml
[project]
name = "bull-run"
version = "0.1.0"
description = "Stock news aggregator with local LLM summarization"
requires-python = ">=3.11"
dependencies = [
    "streamlit>=1.30.0",
    "playwright>=1.40.0",
    "openai>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-mock>=3.12.0",
]
```

- [ ] **Step 2: Install dependencies with uv**

Run: `uv sync --all-extras`
Expected: Dependencies downloaded and virtual environment created

- [ ] **Step 3: Install Playwright Chromium browser binary**

Run: `uv run playwright install chromium`
Expected: Chromium browser downloaded successfully

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: initialize project with uv, streamlit, playwright, openai"
```

---

### Task 2: Scraper Module

**Files:**
- Create: `scraper.py`

- [ ] **Step 1: Write the scraper module**

```python
"""Scrape stock news from Yahoo Finance using Playwright."""

import random
from playwright.sync_api import sync_playwright

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def scrape_news(ticker: str) -> list[dict]:
    """Scrape news articles for a given stock ticker from Yahoo Finance.

    Returns a list of dicts with keys: title, source, date, url, snippet.
    """
    url = f"https://finance.yahoo.com/quote/{ticker}/news/"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for news items to appear
        try:
            page.wait_for_selector("h3", timeout=10000)
        except Exception:
            browser.close()
            return []

        articles = []
        items = page.query_selector_all("h3")

        for heading in items:
            try:
                title = heading.inner_text().strip()
                link_el = heading.query_selector("a")
                url = link_el.get_attribute("href") if link_el else ""

                # Try to find source and date from parent container
                parent = heading.evaluate_handle(
                    "el => el.closest('section') || el.parentElement"
                )
                parent_el = parent.as_element() if parent else None

                source = ""
                date = ""
                snippet = ""

                if parent_el:
                    source_el = parent_el.query_selector(".css-1glg6c2") or parent_el.query_selector("[data-testid='source']")
                    if source_el:
                        source = source_el.inner_text().strip()

                    date_el = parent_el.query_selector(".css-1755hka") or parent_el.query_selector("[data-testid='timestamp']")
                    if date_el:
                        date = date_el.inner_text().strip()

                    snippet_el = parent_el.query_selector(".css-166d938") or parent_el.query_selector("p")
                    if snippet_el:
                        snippet = snippet_el.inner_text().strip()

                if title:
                    articles.append(
                        {
                            "title": title,
                            "source": source,
                            "date": date,
                            "url": url,
                            "snippet": snippet,
                        }
                    )
            except Exception:
                continue

        browser.close()

    return articles[:15]
```

- [ ] **Step 2: Commit**

```bash
git add scraper.py
git commit -m "feat: add Yahoo Finance news scraper with Playwright"
```

---

### Task 3: Scraper Tests

**Files:**
- Create: `tests/test_scraper.py`

- [ ] **Step 1: Write scraper tests**

```python
"""Tests for the scraper module."""

from unittest.mock import MagicMock, patch

from scraper import scrape_news


def test_scrape_news_returns_list_of_dicts_with_expected_keys():
    """Verify scrape_news returns a list of dicts with the correct schema."""
    expected_keys = {"title", "source", "date", "url", "snippet"}

    # Mock the entire Playwright flow
    mock_heading = MagicMock()
    mock_heading.inner_text.return_value = "Test Article Title"
    mock_link = MagicMock()
    mock_link.get_attribute.return_value = "https://example.com/article"
    mock_heading.query_selector.return_value = mock_link

    mock_parent_el = MagicMock()
    mock_parent_el.query_selector.return_value = None
    mock_parent_handle = MagicMock()
    mock_parent_handle.as_element.return_value = mock_parent_el

    mock_page = MagicMock()
    mock_page.query_selector_all.return_value = [mock_heading]
    mock_page.wait_for_selector.return_value = True
    mock_page.goto = MagicMock()
    mock_page.new_page = MagicMock(return_value=mock_page)

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_browser.close = MagicMock()

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch.return_value = mock_browser

    mock_pw = MagicMock()
    mock_pw.__enter__.return_value = mock_pw_instance
    mock_pw.__exit__.return_value = None

    with patch("scraper.sync_playwright", return_value=mock_pw):
        result = scrape_news("AAPL")

    assert isinstance(result, list)
    assert len(result) == 1
    assert set(result[0].keys()) == expected_keys
    assert result[0]["title"] == "Test Article Title"


def test_scrape_news_returns_empty_on_no_results():
    """Verify scrape_news returns empty list when selector times out."""
    mock_page = MagicMock()
    mock_page.wait_for_selector.side_effect = Exception("Timeout")
    mock_page.goto = MagicMock()
    mock_page.new_page = MagicMock(return_value=mock_page)

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_browser.close = MagicMock()

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch.return_value = mock_browser

    mock_pw = MagicMock()
    mock_pw.__enter__.return_value = mock_pw_instance
    mock_pw.__exit__.return_value = None

    with patch("scraper.sync_playwright", return_value=mock_pw):
        result = scrape_news("INVALID")

    assert result == []
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_scraper.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_scraper.py
git commit -m "test: add scraper unit tests with mocked Playwright"
```

---

### Task 4: Summarizer Module

**Files:**
- Create: `summarizer.py`

- [ ] **Step 1: Write the summarizer module**

```python
"""Summarize stock news articles using a local LLM."""

from openai import OpenAI


SYSTEM_PROMPT = """You are a financial news analyst. Given a list of news articles about a stock, provide a concise summary covering:

1. **Key Themes** — What are the main topics trending in the news?
2. **Bullish/Bearish Signals** — Are the overall signals positive, negative, or mixed?
3. **Notable Events** — Any specific events, earnings, or announcements worth highlighting.

Keep the summary under 300 words. Use markdown formatting."""


def summarize_news(articles: list[dict], llm_url: str, model: str) -> str:
    """Send articles to a local LLM and return a markdown summary.

    Args:
        articles: List of dicts with keys: title, source, date, url, snippet.
        llm_url: Base URL of the OpenAI-compatible chat completions endpoint.
        model: Model name to use.

    Returns:
        Markdown summary string from the LLM.
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
        temperature=0.3,
        max_tokens=1000,
    )

    return response.choices[0].message.content or ""
```

- [ ] **Step 2: Commit**

```bash
git add summarizer.py
git commit -m "feat: add LLM summarizer with OpenAI-compatible client"
```

---

### Task 5: Summarizer Tests

**Files:**
- Create: `tests/test_summarizer.py`

- [ ] **Step 1: Write summarizer tests**

```python
"""Tests for the summarizer module."""

from unittest.mock import MagicMock, patch

from summarizer import summarize_news


def test_summarize_news_returns_llm_response():
    """Verify summarize_news sends correct prompt and returns LLM output."""
    articles = [
        {"title": "AAPL Beats Earnings", "source": "Reuters", "date": "2026-05-29", "snippet": "Apple reported strong Q2 results."},
        {"title": "Supply Chain Concerns", "source": "Bloomberg", "date": "2026-05-28", "snippet": "Component shortages may impact production."},
    ]

    mock_message = MagicMock()
    mock_message.content = "## Summary\n\nApple shows strong earnings but faces supply chain headwinds."

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "## Summary\n\nApple shows strong earnings but faces supply chain headwinds."

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("summarizer.OpenAI", return_value=mock_client) as mock_openai:
        result = summarize_news(articles, "http://localhost:8080/v1", "llama3")

    # Verify client was configured with correct base URL
    mock_openai.assert_called_once_with(base_url="http://localhost:8080/v1", api_key="not-needed")

    # Verify the API call included both articles
    call_args = mock_client.chat.completions.create.call_args
    assert call_args.kwargs["model"] == "llama3"
    assert len(call_args.kwargs["messages"]) == 2
    assert "AAPL Beats Earnings" in call_args.kwargs["messages"][1]["content"]
    assert "Supply Chain Concerns" in call_args.kwargs["messages"][1]["content"]

    assert "Summary" in result


def test_summarize_news_handles_empty_articles():
    """Verify summarize_news handles empty article list gracefully."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "No articles to summarize."

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("summarizer.OpenAI", return_value=mock_client):
        result = summarize_news([], "http://localhost:8080/v1", "llama3")

    assert isinstance(result, str)


def test_summarize_news_handles_empty_llm_response():
    """Verify summarize_news returns empty string when LLM returns None content."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("summarizer.OpenAI", return_value=mock_client):
        result = summarize_news([{"title": "Test", "source": "", "date": "", "snippet": ""}], "http://localhost:8080/v1", "llama3")

    assert result == ""
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_summarizer.py -v`
Expected: PASS (3 tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_summarizer.py
git commit -m "test: add summarizer unit tests with mocked OpenAI client"
```

---

### Task 6: Streamlit App

**Files:**
- Create: `app.py`

- [ ] **Step 1: Write the Streamlit application**

```python
"""Streamlit UI for the stock news aggregator."""

import streamlit as st
from scraper import scrape_news
from summarizer import summarize_news

st.set_page_config(page_title="Bull Run — Stock News Aggregator", layout="wide")

st.title("🐂 Bull Run — Stock News Aggregator")


# --- Sidebar Configuration ---
with st.sidebar:
    st.header("Configuration")
    ticker = st.text_input("Stock Ticker", value="AAPL", max_chars=5).upper().strip()
    st.divider()
    st.header("LLM Settings")
    llm_url = st.text_input(
        "LLM Base URL",
        value="http://localhost:8080/v1",
        help="OpenAI-compatible chat completions base URL (e.g., Ollama, LM Studio)",
    )
    model = st.text_input(
        "Model Name",
        value="llama3",
        help="Model name as configured on your LLM server",
    )


# --- Main Panel ---
if not ticker:
    st.warning("Enter a stock ticker to get started.")
elif not llm_url or not model:
    st.warning("Configure your LLM settings in the sidebar.")
else:
    if st.button("📰 Get News", type="primary", use_container_width=True):
        with st.spinner(f"Scraping news for **{ticker}**..."):
            try:
                articles = scrape_news(ticker)
            except Exception as e:
                st.error(f"Failed to scrape news: {e}")
                st.info("Tip: Make sure Playwright browsers are installed — run `playwright install chromium`")
                articles = None

        if articles:
            if not articles:
                st.info(f"No news found for **{ticker}**. Try a different ticker.")
            else:
                # Show raw articles in collapsible section
                with st.expander(f"📋 Raw Articles ({len(articles)})"):
                    for i, article in enumerate(articles, 1):
                        st.markdown(
                            f"**{i}. {article.get('title', 'Untitled')}**\n"
                            f"*{article.get('source', 'Unknown')}* · {article.get('date', '')}\n"
                        )
                        if article.get("snippet"):
                            st.caption(article["snippet"])
                        if article.get("url"):
                            st.caption(f"[Read more]({article['url']})")
                        st.divider()

                # Summarize with LLM
                with st.spinner("Summarizing with LLM..."):
                    try:
                        summary = summarize_news(articles, llm_url, model)
                    except Exception as e:
                        st.error(f"LLM summarization failed: {e}")
                        st.info(f"Check that your LLM server is running at **{llm_url}** with model **{model}**")
                        summary = None

                if summary:
                    st.markdown("## 📝 Summary")
                    st.markdown(summary)

    st.caption("News sourced from Yahoo Finance · Summarized by your local LLM")
```

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "feat: add Streamlit UI with ticker input, LLM config, and results display"
```

---

### Task 7: Run Full Test Suite & Manual Verification

**Files:**
- No new files

- [ ] **Step 1: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS (5 tests total)

- [ ] **Step 2: Start the Streamlit app for manual testing**

Run: `uv run streamlit run app.py`
Expected: App opens in browser at localhost:8501

- [ ] **Step 3: Manual smoke test**

1. Enter a ticker (e.g., `AAPL`) with LLM settings configured
2. Click "Get News"
3. Verify articles are scraped and displayed
4. Verify LLM summary renders as markdown
5. Test with an invalid ticker to verify error handling

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: stock news aggregator complete — scraper, summarizer, Streamlit UI"
```
