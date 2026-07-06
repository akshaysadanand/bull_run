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

# --- State Management (must be before any UI that references these keys) ---
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
if "preset_selector" not in st.session_state:
    st.session_state.preset_selector = ""
if "_preset_ticker" not in st.session_state:
    st.session_state._preset_ticker = None
if "_preset_urls_raw" not in st.session_state:
    st.session_state._preset_urls_raw = None
if "_last_ticker" not in st.session_state:
    st.session_state._last_ticker = "AAPL"
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_tool_calls" not in st.session_state:
    st.session_state.chat_tool_calls = []
if "chat_pending" not in st.session_state:
    st.session_state.chat_pending = None

st.title("🐂 Bull Run — Stock News Aggregator")

# --- Preset Selector Row ---
_presets = load_presets()
_preset_names = [p["name"] for p in _presets] if _presets else []


def on_preset_change():
    """Callback for preset selector — applies preset data and reruns to refresh widgets."""
    _preset_name = st.session_state.get("preset_selector", "")
    _presets_local = load_presets()
    _preset_data = next((p for p in _presets_local if p["name"] == _preset_name), None)
    if _preset_data:
        st.session_state._preset_ticker = _preset_data["ticker"]
        # Sync ticker input widget state so it updates when preset changes
        st.session_state["ticker_input"] = _preset_data["ticker"]
        # Keep _last_ticker in sync so text_input default is correct on reruns
        st.session_state._last_ticker = _preset_data["ticker"]
        _urls = _preset_data.get("custom_urls", [])
        st.session_state._preset_urls_raw = _urls
        # Force the text area to reflect this preset's URLs (overwrites stale widget state)
        st.session_state["custom_urls_area"] = "\n".join(_urls) if _urls else ""
    st.rerun()


def on_preset_run():
    """Callback for preset Run button — loads preset data then triggers news."""
    _preset_name = st.session_state.get("preset_selector", "")
    _presets_local = load_presets()
    _preset_data = next((p for p in _presets_local if p["name"] == _preset_name), None)
    if _preset_data:
        st.session_state._preset_ticker = _preset_data["ticker"]
        st.session_state._last_ticker = _preset_data["ticker"]
        st.session_state._preset_urls_raw = _preset_data.get("custom_urls", [])
    on_get_news()


def on_preset_save():
    """Callback for preset Save button — saves current ticker + sources as a preset."""
    _name = st.session_state.get("_preset_name_input", "").strip()
    if not _name:
        st.error("Preset name is required")
        return
    _ticker_val = st.session_state.get("_current_ticker", ticker)
    _urls_raw = [u.strip() for u in st.session_state.get("_current_urls", "").split("\n") if u.strip()]
    ok = save_preset(_name, _ticker_val, _urls_raw)
    if ok:
        st.toast(f"Preset '{_name}' saved!")
        st.rerun()
    else:
        st.error(f"Preset '{_name}' already exists — choose a different name")


if _preset_names:
    cols = st.columns([3, 0.8, 0.8, 0.2])
    with cols[0]:
        st.selectbox(
            "Quick Presets",
            options=_preset_names,
            key="preset_selector",
            help="Select a preset to load ticker + custom sources",
            on_change=on_preset_change,
        )
    with cols[1]:
        st.button("▶ Run", use_container_width=True, disabled=not st.session_state.preset_selector or st.session_state.progress_step is not None, help="Run news for selected preset", on_click=on_preset_run)
    with cols[2]:
        st.button("+ Save", use_container_width=True, help="Save current ticker + sources as a preset", on_click=on_preset_save)
    with cols[3]:
        st.empty()
else:
    st.info("No presets yet — save one below or create `presets.json`.")

# --- Stock Ticker Selector (main panel) ---
_ticker_default = st.session_state._preset_ticker if st.session_state._preset_ticker else st.session_state._last_ticker
ticker = st.text_input(
    "Stock Ticker",
    value=_ticker_default,
    max_chars=5,
    label_visibility="collapsed",
).upper().strip()
st.session_state._last_ticker = ticker

# Store current values for save preset callback
st.session_state._current_ticker = ticker

# --- Sidebar Configuration ---
with st.sidebar:
    st.header("LLM Settings")
    llm_url = st.selectbox(
        "LLM Base URL",
        options=[
            "http://localhost:8081/v1",
            "http://localhost:8080/v1",
        ],
        help="OpenAI-compatible chat completions base URL (e.g., Ollama, LM Studio)",
    )
    model = st.selectbox(
        "Model Name",
        options=[
            "Qwen3.5-9B-Q8_0.gguf",
            "Qwen3.6-27B-Q8_0.gguf",
        ],
        help="Model name as configured on your LLM server",
    )

    st.divider()

    st.header("Custom Sources")
    _custom_default = "\n".join(st.session_state._preset_urls_raw) if st.session_state._preset_urls_raw else ""
    custom_urls_text = st.text_area(
        "Custom URLs (one per line)",
        value=_custom_default,
        help="Explore custom pages for additional insights (max 20 pages)",
        placeholder="https://example.com/news\nhttps://investor.example.com/earnings",
        key="custom_urls_area",
    )

    st.divider()
    st.header("Save Preset")
    _preset_name = st.text_input(
        "Preset Name",
        key="_preset_name_input",
        help="Name for this preset (e.g., 'Apple', 'Tesla')",
    )
    st.session_state._current_urls = custom_urls_text


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
    st.session_state.chat_history = []
    st.session_state.chat_tool_calls = []
    st.session_state.chat_pending = None
    st.session_state.progress_step = 1
    st.session_state.progress_messages = []
    st.session_state.progress_done = False
    # Use preset URLs if set, otherwise parse from text area
    if st.session_state.get("_preset_urls_raw"):
        st.session_state._custom_urls = st.session_state._preset_urls_raw
    else:
        _urls_text = st.session_state.get("_current_urls", "")
        st.session_state._custom_urls = [u.strip() for u in _urls_text.split("\n") if u.strip()] if _urls_text.strip() else []
    # Clear preset override after use so ticker input isn't locked
    st.session_state._preset_ticker = None
    st.session_state._preset_urls_raw = None
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


def on_chat_send():
    """Callback for chat send (triggered by Enter key) — stores question as pending for streaming."""
    question = st.session_state.get("chat_input", "").strip()
    if not question:
        return

    articles = st.session_state.articles or []
    custom_articles = st.session_state.custom_articles or []
    all_articles = articles + custom_articles
    summary = st.session_state.summary or None

    # Combine Yahoo and custom summaries if both exist
    if st.session_state.custom_summary:
        combined_summary = (summary or "") + "\n\n" + (st.session_state.custom_summary or "")
        summary = combined_summary.strip() or None

    # Store pending question with all context for streaming phase
    st.session_state.chat_pending = {
        "question": question,
        "ticker": ticker,
        "history": st.session_state.chat_history,
        "llm_url": llm_url,
        "model": model,
        "articles": all_articles if all_articles else None,
        "summary": summary,
    }
    st.session_state.chat_tool_calls = []
    st.session_state.chat_input = ""
    st.rerun()


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

# --- Chat Section ---
st.divider()
st.header("💬 Ask about " + (ticker if ticker else "..."))

if ticker:
    # Render chat history
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f"**You:** {msg['content']}")
        elif msg["role"] == "assistant":
            st.markdown(f"**Assistant:** {msg['content']}")

    # Streaming: process pending question
    if st.session_state.chat_pending:
        from chat import ask_followup_stream

        pending = st.session_state.chat_pending
        result = ask_followup_stream(
            question=pending["question"],
            ticker=pending["ticker"],
            history=pending["history"],
            llm_url=pending["llm_url"],
            model=pending["model"],
            articles=pending["articles"],
            summary=pending["summary"],
        )

        # Show tool call progress
        if result["tool_calls"]:
            with st.status("🔍 Searching...", expanded=False) as status:
                for i, tc in enumerate(result["tool_calls"], 1):
                    status.markdown(f"**{i}. web_search** — `{tc.get('query', '')}`")
            st.session_state.chat_tool_calls = result["tool_calls"]

        # Stream the response
        with st.container():
            st.markdown("**Assistant:**")
            full_answer = st.write_stream(result["stream"])

        # Save to history after streaming completes
        st.session_state.chat_history = pending["history"] + [
            {"role": "user", "content": pending["question"]},
            {"role": "assistant", "content": full_answer},
        ]
        st.session_state.chat_pending = None

    # Render tool calls from last response (if any, and not currently streaming)
    elif st.session_state.chat_tool_calls:
        with st.expander("🔧 Tool Calls Made", expanded=False):
            for i, tc in enumerate(st.session_state.chat_tool_calls, 1):
                st.markdown(f"**{i}. web_search** — `{tc.get('query', '')}`")
                tc_result = tc.get("result", "")
                if tc_result:
                    with st.expander("Result"):
                        st.markdown(tc_result)

    # Chat input (Enter to send)
    is_chatting = st.session_state.chat_pending is not None
    st.text_input(
        "Ask a follow-up question",
        key="chat_input",
        placeholder="e.g., What about regulatory risks? Summarize only earnings-related articles.",
        disabled=not ticker or is_chatting,
        on_change=on_chat_send,
    )
else:
    st.info("Enter a ticker to start chatting.")

# ── Run next progress step (after UI renders, triggers rerun) ──
if st.session_state.progress_step is not None:
    run_progress_step()
