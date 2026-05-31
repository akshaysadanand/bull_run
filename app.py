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


# --- State Management ---
if "articles" not in st.session_state:
    st.session_state.articles = None
if "summary" not in st.session_state:
    st.session_state.summary = None
if "summary_error" not in st.session_state:
    st.session_state.summary_error = None


def on_get_news():
    """Callback for the Get News button."""
    st.session_state.articles = None
    st.session_state.summary = None
    st.session_state.summary_error = None

    # Step 1: Scrape
    with st.spinner(f"Scraping news for **{ticker}**..."):
        try:
            st.session_state.articles = scrape_news(ticker)
        except Exception as e:
            st.error(f"Failed to scrape news: {e}")
            st.info("Tip: Make sure Playwright browsers are installed — run `playwright install chromium`")
            st.session_state.articles = []
            return

    # Step 2: Summarize (only if we got articles)
    if st.session_state.articles:
        with st.spinner("Summarizing with LLM..."):
            try:
                st.session_state.summary = summarize_news(
                    st.session_state.articles, llm_url, model
                )
            except Exception as e:
                st.session_state.summary_error = str(e)


# --- Main Panel ---
if not ticker:
    st.warning("Enter a stock ticker to get started.")
elif not llm_url or not model:
    st.warning("Configure your LLM settings in the sidebar.")
else:
    st.button("📰 Get News", type="primary", use_container_width=True, on_click=on_get_news)

    # Show articles if we have them (is not None = button was clicked)
    if st.session_state.articles is not None:
        if not st.session_state.articles:
            st.info(f"No news found for **{ticker}**. Try a different ticker.")
        else:
            # Show raw articles in collapsible section
            with st.expander(f"📋 Raw Articles ({len(st.session_state.articles)})"):
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

    # Always show summary section when articles exist
    if st.session_state.articles:
        st.markdown("## 📝 Summary")

        if st.session_state.summary_error:
            st.error(f"LLM summarization failed: {st.session_state.summary_error}")
            st.info(f"Check that your LLM server is running at **{llm_url}** with model **{model}**")
        elif st.session_state.summary:
            st.markdown(st.session_state.summary)
        else:
            st.info("Waiting for results... Click **Get News** to start.")

    st.caption("News sourced from Yahoo Finance · Summarized by your local LLM")
