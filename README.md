# 🐂 Bull Run — Stock News Aggregator

A local-first stock news aggregator that scrapes financial news and uses a local LLM to produce concise, actionable summaries — no cloud API keys required.

![Stack](https://img.shields.io/badge/Python-3.11+-blue)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-orange)
![Playwright](https://img.shields.io/badge/Scraping-Playwright-green)
![LLM](https://img.shields.io/badge/LLM-Local%20OpenAI--compatible-purple)

## Features

- **Ticker-based news scraping** — Enter any stock ticker and get the latest news from Yahoo Finance
- **Local LLM summarization** — Summaries powered by any OpenAI-compatible local LLM (Ollama, LM Studio, etc.)
- **Custom sources** — Add your own URLs to explore investor pages, earnings reports, or any relevant content
- **Intelligent link discovery** — When using custom sources, the LLM scores and follows the most relevant child links (up to 20 pages)
- **Side-by-side summaries** — Compare Yahoo Finance news with custom source insights in a single view
- **Chain-of-thought visibility** — Toggle to see the LLM's reasoning behind each summary

## Architecture

```
Streamlit UI (app.py)
├── scraper.py       Playwright headless browser → Yahoo Finance + custom URLs
├── summarizer.py    OpenAI-compatible client → local LLM
└── app.py           Streamlit orchestration + UI
```

Three independent modules with clear boundaries:
- **Scraper** — Browser automation, article extraction, link discovery
- **Summarizer** — LLM communication, prompt formatting, response parsing
- **App** — UI, user input, session state, orchestration

## Quick Start

### Prerequisites

- **Python 3.11+**
- **uv** package manager ([install](https://docs.astral.sh/uv/))
- **Playwright browsers** — run `uv run playwright install chromium`
- **Local LLM server** — any OpenAI-compatible endpoint (e.g., Ollama, LM Studio)

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd bull_run

# Install dependencies
uv sync

# Install Playwright browsers
uv run playwright install chromium
```

### Running the App

```bash
uv run streamlit run app.py
```

The app will open at `http://localhost:8501`.

### LLM Setup

Point the app to any OpenAI-compatible chat completions endpoint:

| Server | Base URL | Example Model |
|---|---|---|
| Ollama | `http://localhost:11434/v1` | `qwen2.5:7b` |
| LM Studio | `http://localhost:1234/v1` | (model name as configured) |
| vLLM | `http://localhost:8000/v1` | (model name as configured) |

Configure the URL and model name in the app's sidebar.

## Usage

1. **Enter a stock ticker** (e.g., `AAPL`, `TSLA`, `MSFT`)
2. **Configure your LLM** in the sidebar (base URL + model name)
3. **(Optional) Add custom sources** — paste URLs, one per line, in the "Custom Sources" text area
4. **Click "Get News"** — the app will:
   - Scrape Yahoo Finance for the latest news
   - Explore custom sources (if provided), following relevant child links
   - Summarize both sources independently
   - Display summaries side by side

## Project Structure

```
bull_run/
├── app.py                  Streamlit UI and orchestration
├── scraper.py              Playwright-based news scraping
├── summarizer.py           LLM summarization with chain-of-thought extraction
├── pyproject.toml          Project metadata and dependencies
├── README.md               This file
├── docs/
│   └── superpowers/
│       ├── specs/          Design specifications
│       └── plans/          Implementation plans
└── tests/
    ├── conftest.py         Pytest configuration
    ├── test_scraper.py     Scraper unit tests
    └── test_summarizer.py  Summarizer unit tests
```

## Dependencies

| Package | Purpose |
|---|---|
| `streamlit` | Web UI framework |
| `playwright` | Headless browser automation for scraping |
| `openai` | Client for OpenAI-compatible LLM endpoints |
| `trafilatura` | Content extraction from HTML (strips boilerplate) |

### Dev Dependencies

| Package | Purpose |
|---|---|
| `pytest` | Testing framework |
| `pytest-mock` | Mocking utilities for tests |

## Testing

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_scraper.py -v
```

## Design Documents

Detailed design specs and implementation plans are available in `docs/superpowers/`:

- [Stock News Aggregator Design](docs/superpowers/specs/2026-05-30-stock-news-aggregator-design.md) — Initial architecture and data flow
- [Custom Sources Design](docs/superpowers/specs/2026-05-31-custom-sources-design.md) — Custom URL exploration and LLM-based link scoring

## Privacy & Security

- **No data leaves your machine** — all summarization happens against your local LLM
- **No API keys required** — the `openai` client uses a dummy API key (`not-needed`) for local endpoints
- **Headless browsing** — Playwright runs in headless mode with randomized user agents

## Troubleshooting

| Issue | Solution |
|---|---|
| `playwright` browser not found | Run `uv run playwright install chromium` |
| LLM connection refused | Check that your LLM server is running and the base URL is correct |
| No articles scraped | Yahoo Finance may have changed their DOM — check `scraper.py` selectors |
| Summary is empty or garbled | Try a larger model or increase LLM context window |
| Custom sources timeout | Some sites block headless browsers; try adding a longer timeout in `scraper.py` |

## License

MIT