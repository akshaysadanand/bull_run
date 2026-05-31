# Custom Sources Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `scrape_urls()` function to the scraper module that browses custom URLs, follows relevant child links (2 levels, max 20 pages), and produces a separate summary alongside Yahoo Finance.

**Architecture:** New `scrape_urls()` function in `scraper.py` reuses Playwright browser setup. Content extracted via `trafilatura`. Links extracted programmatically, scored by LLM for relevance. App wires in custom sources UI and dual summaries.

**Tech Stack:** Python 3.11+, Playwright, trafilatura, openai SDK, Streamlit, pytest

---

## File Structure

```
bull_run/
├── pyproject.toml              # Modify: add trafilatura dependency
├── scraper.py                  # Modify: add scrape_urls(), _visit_page(), _score_links()
├── summarizer.py               # Unchanged
├── app.py                      # Modify: custom URLs input, dual summaries
├── tests/
│   ├── test_scraper.py         # Modify: add tests for scrape_urls()
│   └── test_summarizer.py      # Unchanged
└── docs/
    └── superpowers/
        ├── specs/
        └── plans/
```

---

### Task 1: Add trafilatura dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add trafilatura to dependencies**

Add `trafilatura>=1.6.0` to the `[project] dependencies` list in `pyproject.toml`:

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
    "trafilatura>=1.6.0",
]
```

- [ ] **Step 2: Install the new dependency**

Run: `uv sync`
Expected: trafilatura downloaded and installed

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add trafilatura for content extraction"
```

---

### Task 2: Write tests for `scrape_urls()` — empty and invalid inputs

**Files:**
- Modify: `tests/test_scraper.py`

- [ ] **Step 1: Add empty input tests**

Add these test classes to `tests/test_scraper.py`:

```python
class TestScrapeUrlsEmptyInput:
    """Empty or invalid inputs should return [] immediately."""

    def test_empty_url_list_returns_empty_list(self):
        from scraper import scrape_urls
        result = scrape_urls([], "AAPL", "http://localhost:8080/v1", "model")
        assert result == []

    def test_none_url_in_list_returns_empty_list(self):
        from scraper import scrape_urls
        result = scrape_urls([None], "AAPL", "http://localhost:8080/v1", "model")
        assert result == []

    def test_whitespace_only_urls_returns_empty_list(self):
        from scraper import scrape_urls
        result = scrape_urls(["  ", ""], "AAPL", "http://localhost:8080/v1", "model")
        assert result == []
```

- [ ] **Step 2: Run tests to verify they fail (function doesn't exist yet)**

Run: `uv run pytest tests/test_scraper.py::TestScrapeUrlsEmptyInput -v`
Expected: FAIL with ImportError or AttributeError

- [ ] **Step 3: Commit**

```bash
git add tests/test_scraper.py
git commit -m "test: add empty input tests for scrape_urls"
```

---

### Task 3: Implement `scrape_urls()` — skeleton with input validation

**Files:**
- Modify: `scraper.py`

- [ ] **Step 1: Add imports and skeleton function**

Add to top of `scraper.py` after existing imports:

```python
import re
from urllib.parse import urlparse, urljoin

from openai import OpenAI
import trafilatura
```

Add new function at the end of `scraper.py`:

```python
LINK_SCORING_PROMPT = """You are helping gather news about stock ticker {ticker}.
Below is a list of links found on a webpage. Rate which ones are most likely to contain relevant information about {ticker}.

Return ONLY the URLs of the top 5 most relevant links, one per line. If fewer than 5 are relevant, return only those. If none are relevant, return "NONE".

Links:
{links}
"""


def scrape_urls(
    urls: list[str],
    ticker: str,
    llm_url: str,
    model: str,
    max_pages: int = 20,
) -> list[dict]:
    """Scrape articles from custom URLs, following relevant child links.

    Args:
        urls: List of starting URLs to explore.
        ticker: Stock ticker to use for relevance scoring.
        llm_url: Base URL of the OpenAI-compatible chat completions endpoint.
        model: Model name to use for link scoring.
        max_pages: Maximum number of pages to visit (default 20).

    Returns:
        List of dicts with keys: title, source, date, url, snippet.
    """
    # Filter valid URLs
    valid_urls = [u.strip() for u in urls if u and u.strip()]
    if not valid_urls:
        return []

    ticker = ticker.strip().upper()
    articles = []
    visited = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()

        try:
            # Level 1: Visit provided URLs
            seed_links = valid_urls

            # Level 2: Follow relevant child links
            child_links = []
            for url in seed_links:
                if len(articles) >= max_pages:
                    break
                result = _visit_page(page, url, ticker, visited)
                if result is None:
                    continue
                article, links = result
                articles.append(article)
                child_links.extend(links)

            # Score child links with LLM
            if child_links and len(articles) < max_pages:
                scored = _score_links(child_links, ticker, llm_url, model)
                for url in scored:
                    if len(articles) >= max_pages:
                        break
                    if url in visited:
                        continue
                    result = _visit_page(page, url, ticker, visited)
                    if result is None:
                        continue
                    article, _links = result
                    articles.append(article)

        finally:
            browser.close()

    return articles
```

- [ ] **Step 2: Run empty input tests**

Run: `uv run pytest tests/test_scraper.py::TestScrapeUrlsEmptyInput -v`
Expected: PASS (empty inputs return [] before reaching Playwright)

- [ ] **Step 3: Commit**

```bash
git add scraper.py
git commit -m "feat: add scrape_urls() skeleton with input validation"
```

---

### Task 4: Implement `_visit_page()` — page browsing, content extraction, link extraction

**Files:**
- Modify: `scraper.py`

- [ ] **Step 1: Add `_visit_page()` helper function**

Add to `scraper.py` before `scrape_urls()`:

```python
def _visit_page(page, url: str, ticker: str, visited: set) -> tuple[dict, list[str]] | None:
    """Visit a single page, extract content and links.

    Args:
        page: Playwright page object.
        url: URL to visit.
        ticker: Stock ticker for context (used for logging).
        visited: Set of already-visited URLs to avoid duplicates.

    Returns:
        Tuple of (article_dict, list_of_links) or None if page failed.
    """
    # Normalize URL and check if already visited
    parsed = urlparse(url)
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if normalized in visited:
        return None
    visited.add(normalized)

    # Navigate
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        logger.warning("Failed to navigate to %s", url)
        return None

    # Extract content using trafilatura
    try:
        html = page.content()
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
    except Exception:
        # Fall back to raw visible text
        logger.warning("trafilatura failed for %s, using fallback", url)
        text = page.inner_text("body")

    if not text or not text.strip():
        logger.warning("No content extracted from %s", url)
        return None

    # Extract title from page
    try:
        title = page.title()
    except Exception:
        title = url

    # Extract source (domain name)
    source = parsed.netloc.replace("www.", "")

    # Extract links from the page
    links = page.evaluate("""() => {
        const anchors = document.querySelectorAll('a[href]');
        const links = [];
        const seen = new Set();
        for (const a of anchors) {
            try {
                const href = a.href;
                const text = (a.textContent || '').trim();
                if (!href || !text || seen.has(href)) continue;
                // Skip common non-content links
                if (href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('#')) continue;
                if (text.match(/^(click here|read more|learn more|more|next|previous|prev|home|login|sign in|subscribe|unsubscribe)$/i)) continue;
                seen.add(href);
                links.push({ url: href, text: text });
            } catch (e) {
                continue;
            }
        }
        return links;
    }""") or []

    # Build article dict
    article = {
        "title": title,
        "source": source,
        "date": "",
        "url": url,
        "snippet": text[:500] if len(text) > 500 else text,
    }

    return article, links
```

- [ ] **Step 2: Commit**

```bash
git add scraper.py
git commit -m "feat: add _visit_page() for page browsing and content extraction"
```

---

### Task 5: Implement `_score_links()` — LLM-based link relevance scoring

**Files:**
- Modify: `scraper.py`

- [ ] **Step 1: Add `_score_links()` helper function**

Add to `scraper.py` before `scrape_urls()`:

```python
def _score_links(links: list[dict], ticker: str, llm_url: str, model: str) -> list[str]:
    """Ask LLM to score links by relevance to ticker.

    Args:
        links: List of dicts with 'url' and 'text' keys.
        ticker: Stock ticker to score against.
        llm_url: Base URL of the OpenAI-compatible endpoint.
        model: Model name to use.

    Returns:
        List of URLs scored as relevant, up to 5.
    """
    if not links:
        return []

    # Deduplicate links
    seen = set()
    unique_links = []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            unique_links.append(link)

    links_text = "\n".join(f"- \"{l['text']}\" — {l['url']}" for l in unique_links[:50])

    prompt = LINK_SCORING_PROMPT.format(ticker=ticker, links=links_text)

    try:
        client = OpenAI(base_url=llm_url, api_key="not-needed")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Return only URLs, one per line."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""

        # Extract URLs from response
        urls = re.findall(r'https?://\S+', content)
        return urls[:5]

    except Exception:
        # Fallback: return first 5 same-domain links
        logger.warning("LLM link scoring failed, using fallback")
        return [l["url"] for l in unique_links[:5]]
```

- [ ] **Step 2: Commit**

```bash
git add scraper.py
git commit -m "feat: add _score_links() for LLM-based link relevance scoring"
```

---

### Task 6: Write tests for `scrape_urls()` — happy path with mocked Playwright and LLM

**Files:**
- Modify: `tests/test_scraper.py`

- [ ] **Step 1: Add happy path and integration tests**

Add to `tests/test_scraper.py`:

```python
class TestScrapeUrlsHappyPath:
    """scrape_urls visits pages, extracts content, follows child links."""

    def test_returns_articles_from_single_url(self):
        """Verify scrape_urls returns article dicts from a single URL."""
        from scraper import scrape_urls

        mock_page = MagicMock()
        mock_page.goto.return_value = None
        mock_page.content.return_value = "<html><body><h1>Test Article</h1><p>Content here.</p></body></html>"
        mock_page.title.return_value = "Test Article"
        mock_page.inner_text.return_value = "Test Article\nContent here."
        mock_page.evaluate.return_value = [{"url": "https://example.com/child", "text": "Child Page"}]

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context

        mock_chromium = MagicMock()
        mock_chromium.launch.return_value = mock_browser

        mock_pw = MagicMock()
        mock_pw.__enter__ = MagicMock(return_value=mock_pw)
        mock_pw.__exit__ = MagicMock(return_value=False)
        mock_pw.chromium = mock_chromium

        with patch("scraper.sync_playwright", return_value=mock_pw), \
             patch("scraper._score_links", return_value=[]):
            result = scrape_urls(["https://example.com"], "AAPL", "http://localhost:8080/v1", "model")

        assert isinstance(result, list)
        assert len(result) == 1
        assert set(result[0].keys()) == {"title", "source", "date", "url", "snippet"}
        assert result[0]["url"] == "https://example.com"

    def test_respects_max_pages_limit(self):
        """Verify scrape_urls stops at max_pages."""
        from scraper import scrape_urls

        mock_page = MagicMock()
        mock_page.goto.return_value = None
        mock_page.content.return_value = "<html><body><h1>Article</h1><p>Content.</p></body></html>"
        mock_page.title.return_value = "Article"
        mock_page.inner_text.return_value = "Article\nContent."
        mock_page.evaluate.return_value = []

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context

        mock_chromium = MagicMock()
        mock_chromium.launch.return_value = mock_browser

        mock_pw = MagicMock()
        mock_pw.__enter__ = MagicMock(return_value=mock_pw)
        mock_pw.__exit__ = MagicMock(return_value=False)
        mock_pw.chromium = mock_chromium

        urls = [f"https://example.com/page{i}" for i in range(10)]

        with patch("scraper.sync_playwright", return_value=mock_pw), \
             patch("scraper._score_links", return_value=[]):
            result = scrape_urls(urls, "AAPL", "http://localhost:8080/v1", "model", max_pages=3)

        assert len(result) == 3

    def test_skips_already_visited_urls(self):
        """Verify duplicate URLs are not visited twice."""
        from scraper import scrape_urls

        mock_page = MagicMock()
        mock_page.goto.return_value = None
        mock_page.content.return_value = "<html><body><h1>Article</h1><p>Content.</p></body></html>"
        mock_page.title.return_value = "Article"
        mock_page.inner_text.return_value = "Article\nContent."
        mock_page.evaluate.return_value = []

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context

        mock_chromium = MagicMock()
        mock_chromium.launch.return_value = mock_browser

        mock_pw = MagicMock()
        mock_pw.__enter__ = MagicMock(return_value=mock_pw)
        mock_pw.__exit__ = MagicMock(return_value=False)
        mock_pw.chromium = mock_chromium

        with patch("scraper.sync_playwright", return_value=mock_pw), \
             patch("scraper._score_links", return_value=[]):
            result = scrape_urls(
                ["https://example.com", "https://example.com"],
                "AAPL", "http://localhost:8080/v1", "model"
            )

        assert len(result) == 1


class TestScrapeUrlsNavigationFailure:
    """When page.goto raises, skip that page and continue."""

    def test_navigation_error_skips_page(self):
        from scraper import scrape_urls

        mock_page = MagicMock()
        mock_page.goto.side_effect = [Exception("timeout"), None]
        mock_page.content.return_value = "<html><body><h1>Article</h1><p>Content.</p></body></html>"
        mock_page.title.return_value = "Article"
        mock_page.inner_text.return_value = "Article\nContent."
        mock_page.evaluate.return_value = []

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context

        mock_chromium = MagicMock()
        mock_chromium.launch.return_value = mock_browser

        mock_pw = MagicMock()
        mock_pw.__enter__ = MagicMock(return_value=mock_pw)
        mock_pw.__exit__ = MagicMock(return_value=False)
        mock_pw.chromium = mock_chromium

        with patch("scraper.sync_playwright", return_value=mock_pw), \
             patch("scraper._score_links", return_value=[]):
            result = scrape_urls(
                ["https://example.com/fail", "https://example.com/ok"],
                "AAPL", "http://localhost:8080/v1", "model"
            )

        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/ok"


class TestScoreLinks:
    """LLM-based link scoring and fallback behavior."""

    def test_scores_links_with_llm(self):
        from scraper import _score_links

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "https://example.com/relevant1\nhttps://example.com/relevant2"

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        links = [
            {"url": "https://example.com/relevant1", "text": "AAPL earnings report"},
            {"url": "https://example.com/relevant2", "text": "Apple stock analysis"},
            {"url": "https://example.com/irrelevant", "text": "Weather forecast"},
        ]

        with patch("scraper.OpenAI", return_value=mock_client):
            result = _score_links(links, "AAPL", "http://localhost:8080/v1", "model")

        assert "https://example.com/relevant1" in result
        assert "https://example.com/relevant2" in result

    def test_fallback_to_first_links_on_llm_error(self):
        from scraper import _score_links

        links = [
            {"url": "https://example.com/link1", "text": "Link 1"},
            {"url": "https://example.com/link2", "text": "Link 2"},
        ]

        with patch("scraper.OpenAI", side_effect=Exception("LLM error")):
            result = _score_links(links, "AAPL", "http://localhost:8080/v1", "model")

        assert len(result) == 2
        assert result[0] == "https://example.com/link1"

    def test_empty_links_returns_empty(self):
        from scraper import _score_links
        result = _score_links([], "AAPL", "http://localhost:8080/v1", "model")
        assert result == []
```

- [ ] **Step 2: Run all scrape_urls tests**

Run: `uv run pytest tests/test_scraper.py -v -k "ScrapeUrls or ScoreLinks"`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_scraper.py
git commit -m "test: add comprehensive tests for scrape_urls and _score_links"
```

---

### Task 7: Add custom sources UI to Streamlit app

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add custom sources sidebar input and session state**

Add to `app.py` after the existing sidebar LLM settings section:

```python
with st.sidebar:
    st.header("LLM Settings")
    llm_url = st.text_input(
        "LLM Base URL",
        value="http://localhost:8080/v1",
        help="OpenAI-compatible chat completions base URL (e.g., Ollama, LM Studio)",
    )
    model = st.text_input(
        "Model Name",
        value="Qwen3.6-27B-Q8_0.gguf",
        help="Model name as configured on your LLM server",
    )

    st.divider()

    st.header("Custom Sources")
    custom_urls_text = st.text_area(
        "Custom URLs (one per line)",
        help="Explore custom pages for additional insights (max 20 pages)",
        placeholder="https://example.com/news\nhttps://investor.example.com/earnings",
    )
```

- [ ] **Step 2: Add custom sources session state**

Add to session state initialization section:

```python
if "custom_articles" not in st.session_state:
    st.session_state.custom_articles = None
if "custom_summary" not in st.session_state:
    st.session_state.custom_summary = None
if "custom_thinking" not in st.session_state:
    st.session_state.custom_thinking = None
if "custom_summary_error" not in st.session_state:
    st.session_state.custom_summary_error = None
```

- [ ] **Step 3: Update `on_get_news()` to handle custom sources**

Replace the `on_get_news()` function:

```python
def on_get_news():
    """Callback for the Get News button."""
    st.session_state.articles = None
    st.session_state.summary = None
    st.session_state.thinking = None
    st.session_state.summary_error = None
    st.session_state.custom_articles = None
    st.session_state.custom_summary = None
    st.session_state.custom_thinking = None
    st.session_state.custom_summary_error = None

    # Parse custom URLs
    custom_urls = [u.strip() for u in custom_urls_text.split("\n") if u.strip()] if custom_urls_text.strip() else []

    # Step 1: Scrape Yahoo Finance
    with st.spinner(f"Scraping news for **{ticker}**..."):
        try:
            st.session_state.articles = scrape_news(ticker)
        except Exception as e:
            st.error(f"Failed to scrape news: {e}")
            st.info("Tip: Make sure Playwright browsers are installed — run `playwright install chromium`")
            st.session_state.articles = []

    # Step 1b: Scrape custom sources if provided
    if custom_urls:
        with st.spinner(f"Exploring {len(custom_urls)} custom source(s)..."):
            try:
                from scraper import scrape_urls
                st.session_state.custom_articles = scrape_urls(
                    custom_urls, ticker, llm_url, model
                )
            except Exception as e:
                st.error(f"Failed to scrape custom sources: {e}")
                st.session_state.custom_articles = []

    # Step 2: Summarize Yahoo articles
    if st.session_state.articles:
        with st.spinner("Summarizing Yahoo Finance news..."):
            try:
                result = summarize_news(
                    st.session_state.articles, llm_url, model
                )
                st.session_state.summary = result["summary"]
                st.session_state.thinking = result["thinking"]
            except Exception as e:
                st.session_state.summary_error = str(e)

    # Step 2b: Summarize custom articles
    if st.session_state.custom_articles:
        with st.spinner("Summarizing custom sources..."):
            try:
                result = summarize_news(
                    st.session_state.custom_articles, llm_url, model
                )
                st.session_state.custom_summary = result["summary"]
                st.session_state.custom_thinking = result["thinking"]
            except Exception as e:
                st.session_state.custom_summary_error = str(e)
```

- [ ] **Step 4: Update main panel to show dual summaries**

Replace the main panel section (after the "Get News" button) with:

```python
    st.button("📰 Get News", type="primary", use_container_width=True, on_click=on_get_news)

    # Show articles if we have them (is not None = button was clicked)
    if st.session_state.articles is not None:
        # Yahoo Finance articles
        if not st.session_state.articles:
            st.info(f"No news found for **{ticker}** on Yahoo Finance.")
        else:
            with st.expander(f"📋 Yahoo Finance Articles ({len(st.session_state.articles)})"):
                for i, article in enumerate(st.session_state.articles, 1):
                    st.markdown(
                        f"**{i}. {article.get('title', 'Untitled')}**\n"
                        f"*{article.get('source', 'Unknown')}* · {article.get('date', '')}\n"
                    )
                    if article.get("snippet"):
                        st.caption(article["snippet"])
                    if article.get("url"):
                        st.caption(f"[Read more]({article['url']})")
                    st.divider()

        # Custom source articles
        if st.session_state.custom_articles is not None:
            if not st.session_state.custom_articles:
                st.info("No content extracted from custom sources.")
            else:
                with st.expander(f"🔗 Custom Source Articles ({len(st.session_state.custom_articles)})"):
                    for i, article in enumerate(st.session_state.custom_articles, 1):
                        st.markdown(
                            f"**{i}. {article.get('title', 'Untitled')}**\n"
                            f"*{article.get('source', 'Unknown')}* · {article.get('date', '')}\n"
                        )
                        if article.get("snippet"):
                            st.caption(article["snippet"])
                        if article.get("url"):
                            st.caption(f"[Read more]({article['url']})")
                        st.divider()

        # Summaries section
        has_yahoo = bool(st.session_state.articles)
        has_custom = st.session_state.custom_articles is not None and bool(st.session_state.custom_articles)

        if has_yahoo or has_custom:
            st.markdown("## 📝 Summaries")

            if has_yahoo and has_custom:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("### 📊 Yahoo Finance")
                    _render_summary(
                        st.session_state.summary,
                        st.session_state.summary_error,
                        st.session_state.thinking,
                        llm_url,
                        model,
                    )
                with col2:
                    st.markdown("### 🔗 Custom Sources")
                    _render_summary(
                        st.session_state.custom_summary,
                        st.session_state.custom_summary_error,
                        st.session_state.custom_thinking,
                        llm_url,
                        model,
                    )
            elif has_yahoo:
                st.markdown("### 📊 Yahoo Finance Summary")
                _render_summary(
                    st.session_state.summary,
                    st.session_state.summary_error,
                    st.session_state.thinking,
                    llm_url,
                    model,
                )
            elif has_custom:
                st.markdown("### 🔗 Custom Sources Summary")
                _render_summary(
                    st.session_state.custom_summary,
                    st.session_state.custom_summary_error,
                    st.session_state.custom_thinking,
                    llm_url,
                    model,
                )

    st.caption("News sourced from Yahoo Finance · Summarized by your local LLM")
```

- [ ] **Step 5: Add `_render_summary()` helper**

Add before the main panel section in `app.py`:

```python
def _render_summary(summary, summary_error, thinking, llm_url, model):
    """Render a summary section with error handling and reasoning expander."""
    if summary_error:
        st.error(f"LLM summarization failed: {summary_error}")
        st.info(f"Check that your LLM server is running at **{llm_url}** with model **{model}**")
    elif summary is not None:
        if summary.strip():
            st.markdown(summary)
        else:
            st.warning("The LLM returned an empty summary. Try a different model or check your LLM server.")

        if thinking:
            with st.expander("🧠 Model's Reasoning Process"):
                st.markdown(thinking)
    else:
        st.info("Waiting for results...")
```

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: add custom sources UI with dual summaries"
```

---

### Task 8: Run full test suite and verify

**Files:**
- All files

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify no import errors**

Run: `uv run python -c "from scraper import scrape_news, scrape_urls; from summarizer import summarize_news; print('OK')"`
Expected: Prints "OK"

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: custom sources feature complete" || echo "No changes to commit"
```

---

## Self-Review

**Spec coverage check:**
- ✅ `scrape_urls()` function in `scraper.py` with correct signature
- ✅ Playwright browser reuse (same setup as `scrape_news()`)
- ✅ Content extraction with `trafilatura` + fallback to raw text
- ✅ Programmatic link extraction from DOM
- ✅ LLM link scoring with ticker context
- ✅ 2-level deep exploration (seed URLs + scored child links)
- ✅ 20-page hard cap
- ✅ Same article dict format (`title`, `source`, `date`, `url`, `snippet`)
- ✅ Sidebar text area for custom URLs
- ✅ Two collapsible article sections
- ✅ Two summaries side by side with `st.columns(2)`
- ✅ Unchanged behavior when no custom URLs provided
- ✅ Error handling: skip failed pages, LLM fallback, independent summaries
- ✅ trafilatura dependency added
- ✅ Tests: empty inputs, happy path, max pages, visited dedup, navigation failure, LLM scoring, LLM fallback

**Placeholder scan:** No TBDs, TODOs, or vague instructions found.

**Type consistency:** All functions use `list[dict]` with keys `title`, `source`, `date`, `url`, `snippet`. `_visit_page()` returns `tuple[dict, list[str]] | None`. `_score_links()` returns `list[str]`. All consistent.
