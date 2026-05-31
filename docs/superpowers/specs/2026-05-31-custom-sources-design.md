# Custom Sources Feature — Design

## Overview

Extend the stock news aggregator to accept custom URLs from the user. The system browses those URLs, intelligently follows relevant child links (2 levels deep, max 20 pages), extracts content, and produces a separate summary alongside the Yahoo Finance summary.

## Architecture

```
Streamlit UI (app.py)
├── scraper.py
│   ├── scrape_news(ticker) → list[dict]              # existing — Yahoo Finance
│   └── scrape_urls(urls, ticker, llm_url, model) → list[dict]  # new — custom sources
├── summarizer.py
│   └── summarize_news(articles, llm_url, model) → dict  # unchanged
└── app.py
    └── UI: ticker + custom URLs → two summaries side by side
```

Module boundaries:
- **Scraper** owns all browser automation and article extraction (Yahoo + custom sources)
- **Summarizer** owns LLM communication and prompt formatting
- **App** owns UI, user input, and orchestration

## Components

### Scraper — `scrape_urls()` (new function in `scraper.py`)

- **Signature:** `scrape_urls(urls: list[str], ticker: str, llm_url: str, model: str, max_pages: int = 20) -> list[dict]`
- **Returns:** Same `list[dict]` format as `scrape_news()`: `title`, `source`, `date`, `url`, `snippet`

**Flow:**
1. For each provided URL, launch Playwright (reuse existing browser setup, user-agent rotation)
2. Navigate to the page, wait for content to load (`domcontentloaded`, 30s timeout)
3. Extract main content using `trafilatura` from the page's HTML — strips navigation, ads, boilerplate
4. Extract all `<a href>` links programmatically from the rendered DOM
5. Send link text + URLs + ticker to LLM for relevance scoring — LLM returns top 5 most relevant links
6. Follow those links (level 2), repeating steps 2-4 (content extraction only, no deeper link following)
7. Enforce 20-page hard cap across all custom sources
8. Return collected articles

**LLM link scoring prompt:**
- Input: list of link texts and URLs from the current page, plus the ticker symbol
- Task: "Which of these links are most relevant to {ticker}? Return the top 5 URLs."
- Cost: ~100-200 tokens per page (link text only, no page content)
- Response parsing: extract URLs from LLM response, validate they are absolute URLs

### Streamlit App — UI Changes

**Sidebar additions:**
- "Custom Sources" section with a multi-line text area
- One URL per line
- Info text: "Explore custom pages for additional insights (max 20 pages)"

**Main panel changes:**
- When custom URLs are provided, two collapsible article sections appear: "📋 Yahoo Finance Articles" and "🔗 Custom Source Articles"
- Two summaries displayed side by side using `st.columns(2)`: "📊 Yahoo Finance Summary" and "🔗 Custom Sources Summary"
- When no custom URLs are provided, behavior is unchanged (single Yahoo summary)

## Data Flow

1. User enters ticker + optional custom URLs in sidebar
2. User clicks "Get News"
3. `scrape_news(ticker)` runs → Yahoo articles
4. If custom URLs provided: `scrape_urls(urls, ticker, llm_url, model)` runs → custom articles
5. Summarizer called separately for each set:
   - `summarize_news(yahoo_articles, ...)` → Yahoo summary
   - `summarize_news(custom_articles, ...)` → Custom sources summary
6. Both summaries render side by side

## Error Handling

| Scenario | Behavior |
|---|---|
| Page navigation fails | Skip page, log warning, continue with remaining pages |
| LLM link scoring fails | Fall back to first 5 same-domain links |
| All custom sources fail | Show error for custom sources; Yahoo summary still works independently |
| 20-page cap reached | Stop exploration, summarize collected content |
| `trafilatura` extraction fails | Fall back to raw visible text from Playwright |

## Dependencies

- **New:** `trafilatura` — lightweight content extraction from HTML
- **Existing:** `playwright`, `openai`, `streamlit`

## Testing

- Mock Playwright for `scrape_urls()` — verify link extraction, LLM scoring calls, page cap enforcement
- Mock LLM client — verify link scoring prompt format and response parsing
- Verify both scrapers return compatible article dicts with same keys
- Test fallback when LLM scoring fails (same-domain link fallback)
- Test empty URL list returns empty article list
