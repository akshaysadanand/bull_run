"""Scrape stock news from Yahoo Finance using Playwright."""

import logging
import os
import random
import re
from urllib.parse import urlparse, urljoin

from openai import OpenAI
from playwright.sync_api import sync_playwright

import trafilatura

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def scrape_news(ticker: str) -> list[dict]:
    """Scrape news articles for a given stock ticker from Yahoo Finance.

    Returns a list of dicts with keys: title, source, date, url, snippet.
    Max 15 articles. Returns empty list on failure.
    """
    ticker = ticker.strip().upper()
    if not ticker:
        return []

    url = f"https://finance.yahoo.com/quote/{ticker}/news/"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            logger.exception("Failed to navigate to %s", url)
            browser.close()
            return []

        # Wait for JS-rendered news stream to appear
        try:
            page.wait_for_selector('[data-testid="news-stream"]', timeout=15000)
        except Exception:
            logger.exception("News stream not found for %s", ticker)
            browser.close()
            return []

        # Extract articles using JavaScript evaluation for reliability
        articles = page.evaluate("""() => {
            const stream = document.querySelector('[data-testid="news-stream"]');
            if (!stream) return [];

            const items = stream.querySelectorAll('[data-testid="storyitem"]');
            const articles = [];

            for (const item of items) {
                try {
                    // Title from the titles link's h3
                    const titleLink = item.querySelector('.content a[class*="titles"]');
                    if (!titleLink) continue;

                    const h3 = titleLink.querySelector('h3');
                    const title = h3 ? h3.textContent.trim() : titleLink.textContent.trim();
                    const articleUrl = titleLink.href || '';
                    if (!title || !articleUrl) continue;

                    // Source and date from the publishing div
                    let source = '';
                    let date = '';
                    const publishing = item.querySelector('.publishing');
                    if (publishing) {
                        const text = publishing.textContent.trim();
                        // Format: "Source Name • Xh ago" or "Source Name • X days ago"
                        const parts = text.split('•');
                        if (parts.length >= 2) {
                            source = parts[0].trim();
                            date = parts.slice(1).join('•').trim();
                        } else {
                            source = text;
                        }
                    }

                    // Snippet - not available in the stream view, leave empty
                    const snippet = '';

                    articles.push({
                        title: title,
                        source: source,
                        date: date,
                        url: articleUrl,
                        snippet: snippet,
                    });
                } catch (e) {
                    continue;
                }
            }

            return articles.slice(0, 15);
        }""")

        browser.close()

    # Keep only articles that actually mention the ticker in the title
    articles = [a for a in (articles or []) if ticker in a.get("title", "")]

    return articles or []


# ── Custom Sources ───────────────────────────────────────────────────────

LINK_SCORING_PROMPT = """You are helping gather news about stock ticker {ticker}.
Below is a list of links found on a webpage. Rate which ones are most likely to contain relevant information about {ticker}.

Return ONLY the URLs of the top 5 most relevant links, one per line. If fewer than 5 are relevant, return only those. If none are relevant, return "NONE".

Links:
{links}
"""


SKIP_EXTENSIONS = {".pdf", ".zip", ".tar", ".gz", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mp3", ".avi"}


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

    # Skip non-HTML resources (PDFs, images, archives, etc.)
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in SKIP_EXTENSIONS:
        logger.info("Skipping non-HTML resource: %s", url)
        return None

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
