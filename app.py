"""Streamlit UI for the stock news aggregator."""

import streamlit as st
from scraper import scrape_news
from summarizer import summarize_news

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
