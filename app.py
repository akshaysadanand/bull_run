"""Streamlit UI for the stock news aggregator."""

import json
from pathlib import Path

import streamlit as st
from scraper import scrape_news
from summarizer import summarize_news

PRESETS_FILE = Path(__file__).parent / "presets.json"


def load_presets() -> list[dict]:
    """Load presets from presets.json. Returns empty list on any error."""
    path = Path(PRESETS_FILE)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            return []
        return data
    except (json.JSONDecodeError, OSError):
        return []


def save_preset(name: str, ticker: str, custom_urls: list[str]) -> bool:
    """Append a preset to presets.json. Returns False if name already exists."""
    if not name.strip():
        return False

    presets = load_presets()
    for p in presets:
        if p.get("name", "").strip().upper() == name.strip().upper():
            return False

    presets.append({
        "name": name.strip(),
        "ticker": ticker.strip().upper(),
        "custom_urls": custom_urls,
    })
    Path(PRESETS_FILE).write_text(json.dumps(presets, indent=2) + "\n")
    return True


st.set_page_config(page_title="Bull Run — Stock News Aggregator", layout="wide")

st.title("🐂 Bull Run — Stock News Aggregator")

# --- Stock Ticker Selector (main panel) ---
ticker = st.text_input(
    "Stock Ticker",
    value="AAPL",
    max_chars=5,
    label_visibility="collapsed",
).upper().strip()


# --- Sidebar Configuration ---
with st.sidebar:
    st.header("LLM Settings")
    llm_url = st.selectbox(
        "LLM Base URL",
        options=[
            "http://localhost:8080/v1",
            "http://localhost:8081/v1",
        ],
        help="OpenAI-compatible chat completions base URL (e.g., Ollama, LM Studio)",
    )
    model = st.selectbox(
        "Model Name",
        options=[
            "Qwen3.6-27B-Q8_0.gguf",
            "Qwen3.5-9B-Q8_0.gguf",
        ],
        help="Model name as configured on your LLM server",
    )

    st.divider()

    st.header("Custom Sources")
    custom_urls_text = st.text_area(
        "Custom URLs (one per line)",
        help="Explore custom pages for additional insights (max 20 pages)",
        placeholder="https://example.com/news\nhttps://investor.example.com/earnings",
    )


# --- State Management ---
if "articles" not in st.session_state:
    st.session_state.articles = None
if "summary" not in st.session_state:
    st.session_state.summary = None
if "thinking" not in st.session_state:
    st.session_state.thinking = None
if "summary_error" not in st.session_state:
    st.session_state.summary_error = None
if "custom_articles" not in st.session_state:
    st.session_state.custom_articles = None
if "custom_summary" not in st.session_state:
    st.session_state.custom_summary = None
if "custom_thinking" not in st.session_state:
    st.session_state.custom_thinking = None
if "custom_summary_error" not in st.session_state:
    st.session_state.custom_summary_error = None
if "progress_step" not in st.session_state:
    st.session_state.progress_step = None
if "progress_messages" not in st.session_state:
    st.session_state.progress_messages = []
if "progress_done" not in st.session_state:
    st.session_state.progress_done = False


def on_get_news():
    """Callback for the Get News button — resets state and starts step 1."""
    st.session_state.articles = None
    st.session_state.summary = None
    st.session_state.thinking = None
    st.session_state.summary_error = None
    st.session_state.custom_articles = None
    st.session_state.custom_summary = None
    st.session_state.custom_thinking = None
    st.session_state.custom_summary_error = None
    st.session_state.progress_step = 1
    st.session_state.progress_messages = []
    st.session_state.progress_done = False
    st.session_state._custom_urls = [u.strip() for u in custom_urls_text.split("\n") if u.strip()] if custom_urls_text.strip() else []
    st.rerun()


def run_progress_step():
    """Execute one step of the pipeline, then rerun to update the UI."""
    step = st.session_state.progress_step
    custom_urls = st.session_state.get("_custom_urls", [])

    if step == 1:
        # Scrape Yahoo Finance
        st.session_state.progress_messages.append(f"🔍 Scraping Yahoo Finance for **{ticker}**...")
        try:
            st.session_state.articles = scrape_news(ticker)
            st.session_state.progress_messages.append(f"✅ Found **{len(st.session_state.articles)}** article(s) from Yahoo Finance")
        except Exception as e:
            st.session_state.progress_messages.append(f"❌ Yahoo Finance scraping failed: {e}")
            st.session_state.articles = []
        st.session_state.progress_step = 2
        st.rerun()

    elif step == 2:
        # Scrape custom sources (if any)
        if custom_urls:
            st.session_state.progress_messages.append(f"🔗 Exploring **{len(custom_urls)}** custom source(s)...")
            try:
                from scraper import scrape_urls
                st.session_state.custom_articles = scrape_urls(
                    custom_urls, ticker, llm_url, model
                )
                st.session_state.progress_messages.append(f"✅ Extracted **{len(st.session_state.custom_articles)}** article(s) from custom sources")
            except Exception as e:
                st.session_state.progress_messages.append(f"❌ Custom source scraping failed: {e}")
                st.session_state.custom_articles = []
        st.session_state.progress_step = 3
        st.rerun()

    elif step == 3:
        # Summarize Yahoo articles
        if st.session_state.articles:
            st.session_state.progress_messages.append(f"🤖 Summarizing **{len(st.session_state.articles)}** Yahoo Finance article(s) with LLM...")
            try:
                result = summarize_news(
                    st.session_state.articles, llm_url, model
                )
                st.session_state.summary = result["summary"]
                st.session_state.thinking = result["thinking"]
                st.session_state.progress_messages.append("✅ Yahoo Finance summary complete")
            except Exception as e:
                st.session_state.summary_error = str(e)
                st.session_state.progress_messages.append(f"❌ Yahoo Finance summarization failed: {e}")
        st.session_state.progress_step = 4
        st.rerun()

    elif step == 4:
        # Summarize custom articles
        if st.session_state.custom_articles:
            st.session_state.progress_messages.append(f"🤖 Summarizing **{len(st.session_state.custom_articles)}** custom source article(s) with LLM...")
            try:
                result = summarize_news(
                    st.session_state.custom_articles, llm_url, model
                )
                st.session_state.custom_summary = result["summary"]
                st.session_state.custom_thinking = result["thinking"]
                st.session_state.progress_messages.append("✅ Custom sources summary complete")
            except Exception as e:
                st.session_state.custom_summary_error = str(e)
                st.session_state.progress_messages.append(f"❌ Custom sources summarization failed: {e}")
        st.session_state.progress_step = None
        st.session_state.progress_done = True
        st.rerun()


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


# --- Main Panel ---
if not ticker:
    st.warning("Enter a stock ticker to get started.")
elif not llm_url or not model:
    st.warning("Configure your LLM settings in the sidebar.")
else:
    is_working = st.session_state.progress_step is not None
    st.button("📰 Get News", type="primary", use_container_width=True, on_click=on_get_news, disabled=is_working)

    # Progress status box — renders from session state, updates via rerun()
    if is_working:
        with st.status(f"🔍 Gathering news for **{ticker}**...", expanded=True) as status:
            for msg in st.session_state.progress_messages:
                status.markdown(msg)
            status.markdown("⏳ Working...")
    elif st.session_state.progress_done:
        with st.status("✅ Done — results below", state="complete", expanded=False) as status:
            for msg in st.session_state.progress_messages:
                status.markdown(msg)

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

# ── Run next progress step (after UI renders, triggers rerun) ──
if st.session_state.progress_step is not None:
    run_progress_step()
