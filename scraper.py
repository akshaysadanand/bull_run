"""Scrape stock news from Yahoo Finance using Playwright."""

import logging
import random
from playwright.sync_api import sync_playwright

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
    articles = [a for a in articles if ticker in a.get("title", "")]

    return articles or []
