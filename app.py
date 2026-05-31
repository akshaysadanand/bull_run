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
