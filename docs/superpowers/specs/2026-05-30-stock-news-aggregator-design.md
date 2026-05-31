# Stock News Aggregator — Design

## Overview

A Streamlit web application that takes a stock ticker, scrapes relevant news from Yahoo Finance using a headless Playwright browser, and summarizes the articles using a local LLM with a chat completions API.

## Architecture

```
Streamlit UI (app.py)
├── scraper.py    (Playwright headless browser → Yahoo Finance)
├── summarizer.py (OpenAI-compatible client → local LLM)
└── app.py        (Streamlit orchestration + UI)
```

Three independent modules with clear boundaries:
- **Scraper** owns browser automation and article extraction
- **Summarizer** owns LLM communication and prompt formatting
- **App** owns UI, user input, and orchestration

## Components

### Scraper (`scraper.py`)

- **Function:** `scrape_news(ticker: str) -> list[dict]`
- Launches a headless Playwright Chromium browser
- Navigates to `https://finance.yahoo.com/{ticker}/news`
- Extracts per article: `title`, `source`, `date`, `url`, `snippet`
- Returns list of article dictionaries
- Closes browser context after scraping
- Uses randomized User-Agent header for additional stealth

### Summarizer (`summarizer.py`)

- **Function:** `summarize_news(articles: list[dict], llm_url: str, model: str) -> str`
- Formats articles into a structured prompt (title + snippet per article)
- Uses the `openai` Python client with a custom `base_url` pointing to the local LLM
- Prompt asks the LLM to produce: key themes, bullish/bearish signals, and notable events
- Returns the LLM response as a markdown string

### Streamlit App (`app.py`)

- **Sidebar:** Ticker input, LLM base URL input, model name input
- **Main panel:** "Get News" button, loading spinner during processing, markdown summary output
- **Collapsible section:** Raw article list (title, source, date, link) for reference
- Uses `@st.cache_data` for repeated ticker lookups within a session

## Data Flow

1. User enters ticker (e.g., `AAPL`) and LLM configuration in the sidebar
2. User clicks "Get News"
3. App calls `scraper.scrape_news(ticker)` → Playwright scrapes Yahoo Finance → returns ~10-15 articles
4. App calls `summarizer.summarize_news(articles, llm_url, model)` → local LLM returns summary
5. Summary renders as markdown; raw articles available in a collapsible section

## Error Handling

| Scenario | Behavior |
|---|---|
| Scraping fails | User-friendly error message; suggest checking connection or retrying |
| LLM call fails | Show error with the failed endpoint; allow retry |
| No news found | Display "No news found for {ticker}" |
| Playwright browser missing | Detect and show `playwright install chromium` instructions |

## Tech Stack

- **Language:** Python 3.11+
- **Package manager:** uv
- **UI:** Streamlit
- **Browser automation:** Playwright (headless Chromium)
- **LLM client:** `openai` Python SDK (custom base URL for any OpenAI-compatible server)

## Testing

- Manual testing via Streamlit with known tickers (`AAPL`, `TSLA`, `MSFT`)
- Scraper: verify non-empty list of dicts with expected keys
- Summarizer: mock the OpenAI client to verify prompt formatting and response handling
