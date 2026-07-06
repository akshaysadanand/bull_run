# Follow-Up Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a multi-turn chat interface with web search tool calling that works both as a follow-up to scraped articles and as a standalone financial analyst chatbot.

**Architecture:** New `chat.py` module handles LLM conversation + tool-calling loop. `app.py` adds chat UI section and session state. No new dependencies — uses existing `openai` client (tool calling via `tools=` param) and SearXNG HTTP API at `http://localhost:8088`.

**Tech Stack:** Python, Streamlit, OpenAI Python SDK (tool calling), SearXNG HTTP API, `urllib.request` (stdlib HTTP for web search)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `chat.py` | Create | Multi-turn chat logic, system prompt building, tool-calling loop, web search execution |
| `tests/test_chat.py` | Create | Unit tests for `ask_followup()`, tool calling, both modes |
| `app.py` | Modify | Chat UI section, session state, `on_chat_send()` callback |

---

### Task 1: Web search helper function

**Files:**
- Create: `chat.py`
- Test: `tests/test_chat.py`

The web search function that `chat.py` uses internally to query SearXNG. Pure function — takes a query string, returns formatted text.

- [ ] **Step 1: Write the failing test**

Create `tests/test_chat.py`:

```python
"""Tests for the chat module."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_web_search_returns_formatted_results():
    """Verify web_search formats SearXNG results into readable text."""
    from chat import _web_search

    mock_json = {
        "results": [
            {
                "title": "AAPL Earnings Beat",
                "url": "https://example.com/aapl-earnings",
                "content": "Apple reported strong Q2 results beating expectations.",
            },
            {
                "title": "AAPL Stock Analysis",
                "url": "https://example.com/aapl-analysis",
                "content": "Analysts raise price target on strong iPhone sales.",
            },
        ]
    }

    with patch("chat.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = str(mock_json).encode()
        mock_response.getheader.return_value = "application/json"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # We need to mock json.loads since urlopen returns bytes
        with patch("chat.json.loads", return_value=mock_json):
            result = _web_search("AAPL earnings")

    assert "AAPL Earnings Beat" in result
    assert "AAPL Stock Analysis" in result
    assert "example.com/aapl-earnings" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py::test_web_search_returns_formatted_results -v`
Expected: FAIL with "cannot import name '_web_search' from 'chat'"

- [ ] **Step 3: Write minimal implementation**

Create `chat.py`:

```python
"""Multi-turn chat with web search tool calling for stock news analysis."""

import json
import logging
from typing import Optional
from urllib.parse import quote_plus
from urllib.request import urlopen

logger = logging.getLogger(__name__)

SEARXNG_URL = "http://localhost:8088"
MAX_SEARCH_ITERATIONS = 3
MAX_CHAT_TURNS = 10


def _web_search(query: str) -> str:
    """Search the web via SearXNG and return formatted text results.

    Args:
        query: Search query string.

    Returns:
        Formatted text with titles, URLs, and snippets from top results.
        Empty string on failure.
    """
    url = f"{SEARXNG_URL}/search?q={quote_plus(query)}&format=json"
    try:
        with urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())

    except Exception as e:
        logger.exception("Web search failed for query: %s", query)
        return f"Search failed: {e}"

    results = data.get("results", [])
    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results[:5], 1):
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        content = r.get("content", "")
        lines.append(f"[{i}] {title}")
        if url:
            lines.append(f"    URL: {url}")
        if content:
            lines.append(f"    {content[:300]}")
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py::test_web_search_returns_formatted_results -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chat.py tests/test_chat.py
git commit -m "feat: add web search helper for SearXNG"
```

---

### Task 2: Web search error handling

**Files:**
- Modify: `chat.py`
- Test: `tests/test_chat.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chat.py`:

```python
def test_web_search_handles_connection_error():
    """Verify web_search returns error message on connection failure."""
    from chat import _web_search

    with patch("chat.urlopen", side_effect=Exception("Connection refused")):
        result = _web_search("test query")

    assert "Search failed" in result
    assert "Connection refused" in result


def test_web_search_handles_empty_results():
    """Verify web_search handles empty result set."""
    from chat import _web_search

    with patch("chat.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"results": []}'
        mock_response.getheader.return_value = "application/json"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with patch("chat.json.loads", return_value={"results": []}):
            result = _web_search("test query")

    assert "No results found" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py::test_web_search_handles_connection_error tests/test_chat.py::test_web_search_handles_empty_results -v`
Expected: At least one FAIL (empty results case may already pass)

- [ ] **Step 3: Verify implementation already handles these cases**

The current `_web_search` implementation already handles both cases:
- `except Exception` catches connection errors → returns "Search failed: ..."
- `if not results` checks for empty list → returns "No results found."

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add chat.py tests/test_chat.py
git commit -m "test: add web search error handling tests"
```

---

### Task 3: System prompt builder

**Files:**
- Modify: `chat.py`
- Test: `tests/test_chat.py`

Builds the system prompt based on available context (follow-up vs standalone mode).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chat.py`:

```python
def test_build_system_prompt_followup_mode():
    """Verify system prompt includes articles and summary in follow-up mode."""
    from chat import _build_system_prompt

    articles = [
        {"title": "AAPL Earnings Beat", "source": "Reuters", "date": "2026-07-01", "snippet": "Strong Q2 results."},
    ]
    summary = "Apple shows strong earnings."

    prompt = _build_system_prompt("AAPL", articles, summary)

    assert "AAPL" in prompt
    assert "Apple shows strong earnings" in prompt
    assert "AAPL Earnings Beat" in prompt
    assert "web_search" in prompt


def test_build_system_prompt_standalone_mode():
    """Verify system prompt omits article context in standalone mode."""
    from chat import _build_system_prompt

    prompt = _build_system_prompt("TSLA", None, None)

    assert "TSLA" in prompt
    assert "INITIAL SUMMARY" not in prompt
    assert "ARTICLES" not in prompt
    assert "web_search" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py::test_build_system_prompt_followup_mode tests/test_chat.py::test_build_system_prompt_standalone_mode -v`
Expected: FAIL with "cannot import name '_build_system_prompt' from 'chat'"

- [ ] **Step 3: Write implementation**

Add to `chat.py`:

```python

def _build_system_prompt(
    ticker: str,
    articles: Optional[list[dict]],
    summary: Optional[str],
) -> str:
    """Build system prompt based on available context.

    Args:
        ticker: Stock ticker symbol.
        articles: Scraped articles (optional).
        summary: Initial summary from summarizer (optional).

    Returns:
        System prompt string tailored to available context.
    """
    if articles and summary:
        articles_text = "\n".join(
            f"- {a.get('title', 'Untitled')} ({a.get('source', 'Unknown')}, {a.get('date', '')})"
            for a in articles
        )
        return (
            f"You are a financial news analyst helping a user understand news about {ticker}.\n"
            f"You have access to the following context:\n\n"
            f"INITIAL SUMMARY:\n{summary}\n\n"
            f"ARTICLES:\n{articles_text}\n\n"
            f"Answer the user's question based on this context. "
            f"If you need additional current information, use the web_search tool. "
            f"Be concise and cite sources when referencing specific claims."
        )
    else:
        return (
            f"You are a financial news analyst helping a user research {ticker}.\n"
            f"Use the web_search tool to find current information. "
            f"Be concise and cite sources when referencing specific claims."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py::test_build_system_prompt_followup_mode tests/test_chat.py::test_build_system_prompt_standalone_mode -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chat.py tests/test_chat.py
git commit -m "feat: add system prompt builder for follow-up and standalone modes"
```

---

### Task 4: `ask_followup()` — basic text response (no tool calls)

**Files:**
- Modify: `chat.py`
- Test: `tests/test_chat.py`

Core function — handles the simple case where LLM returns text directly.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chat.py`:

```python
def test_ask_followup_returns_text_response():
    """Verify ask_followup returns LLM text response and updated history."""
    from chat import ask_followup

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Based on the articles, AAPL shows strong earnings growth."
    mock_response.choices[0].message.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("chat.OpenAI", return_value=mock_client) as mock_openai:
        result = ask_followup(
            question="How are AAPL earnings?",
            ticker="AAPL",
            history=[],
            llm_url="http://localhost:8080/v1",
            model="qwen",
            articles=[{"title": "Earnings Beat", "source": "Reuters", "date": "2026-07-01", "snippet": "Strong results."}],
            summary="AAPL shows strong earnings.",
        )

    assert "earnings growth" in result["answer"]
    assert len(result["history"]) == 2  # user + assistant
    assert result["history"][0]["role"] == "user"
    assert result["history"][1]["role"] == "assistant"

    # Verify LLM was called with tools parameter
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert "tools" in call_kwargs
    assert len(call_kwargs["tools"]) == 1
    assert call_kwargs["tools"][0]["function"]["name"] == "web_search"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py::test_ask_followup_returns_text_response -v`
Expected: FAIL with "cannot import name 'ask_followup' from 'chat'"

- [ ] **Step 3: Write implementation**

Add to `chat.py`:

```python
from openai import OpenAI


WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information about a topic",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                }
            },
            "required": ["query"]
        }
    }
}


def ask_followup(
    question: str,
    ticker: str,
    history: list[dict],
    llm_url: str,
    model: str,
    articles: Optional[list[dict]] = None,
    summary: Optional[str] = None,
) -> dict:
    """Process a follow-up question with multi-turn chat and web search tool calling.

    Args:
        question: User's question.
        ticker: Stock ticker symbol.
        history: Prior chat messages [{role, content}, ...].
        llm_url: OpenAI-compatible LLM base URL.
        model: Model name.
        articles: Optional scraped articles for context.
        summary: Optional initial summary for context.

    Returns:
        Dict with 'answer' (LLM response text) and 'history' (updated message list).
    """
    if not question.strip():
        return {"answer": "", "history": history}

    client = OpenAI(base_url=llm_url, api_key="not-needed")

    system_prompt = _build_system_prompt(ticker, articles, summary)

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # Trim history to last MAX_CHAT_TURNS turns if needed
    trimmed_history = history[-(MAX_CHAT_TURNS * 2):] if len(history) > MAX_CHAT_TURNS * 2 else history
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": question})

    # Tool-calling loop (max MAX_SEARCH_ITERATIONS iterations)
    for _ in range(MAX_SEARCH_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[WEB_SEARCH_TOOL],
                temperature=0.1,
            )
        except Exception as e:
            logger.exception("LLM call failed, falling back to text-only")
            # Retry without tools
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.1,
                )
            except Exception as e2:
                return {"answer": f"LLM error: {e2}", "history": history}

        message = response.choices[0].message

        if message.tool_calls:
            # Execute tool calls and append results
            for tool_call in message.tool_calls:
                if tool_call.function.name == "web_search":
                    args = json.loads(tool_call.function.arguments)
                    query = args.get("query", "")
                    search_result = _web_search(query)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": search_result,
                    })

            # Also append the assistant's tool call message
            messages.append({
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in message.tool_calls
                ],
            })
            continue  # Loop back to call LLM again with tool results

        # Text response — done
        answer = message.content or ""
        new_history = trimmed_history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
        return {"answer": answer, "history": new_history}

    # Exceeded max iterations
    return {
        "answer": "I've reached my search limit. Based on what I found, let me provide my best answer with the information available.",
        "history": history,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py::test_ask_followup_returns_text_response -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chat.py tests/test_chat.py
git commit -m "feat: implement ask_followup with tool calling loop"
```

---

### Task 5: `ask_followup()` — tool calling flow

**Files:**
- Modify: `chat.py`
- Test: `tests/test_chat.py`

Test that the LLM's tool calls are executed and results fed back.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chat.py`:

```python
def test_ask_followup_executes_tool_calls():
    """Verify ask_followup executes web_search tool calls and loops back."""
    from chat import ask_followup

    # First call: LLM requests web search
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "web_search"
    mock_tool_call.function.arguments = '{"query": "AAPL latest news"}'

    mock_response_tool = MagicMock()
    mock_response_tool.choices[0].message.content = None
    mock_response_tool.choices[0].message.tool_calls = [mock_tool_call]

    # Second call: LLM returns text answer after seeing search results
    mock_response_text = MagicMock()
    mock_response_text.choices[0].message.content = "Based on recent news, AAPL announced new products."
    mock_response_text.choices[0].message.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [mock_response_tool, mock_response_text]

    with patch("chat.OpenAI", return_value=mock_client):
        with patch("chat._web_search", return_value="[1] AAPL New Product Launch\n    URL: https://example.com\n    Apple announces new lineup."):
            result = ask_followup(
                question="What's new with AAPL?",
                ticker="AAPL",
                history=[],
                llm_url="http://localhost:8080/v1",
                model="qwen",
            )

    # Verify LLM was called twice (tool call + final answer)
    assert mock_client.chat.completions.create.call_count == 2
    assert "new products" in result["answer"]
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py::test_ask_followup_executes_tool_calls -v`
Expected: PASS (implementation from Task 4 already handles this)

- [ ] **Step 3: If test fails, fix implementation**

If the test fails, review the tool-calling loop in `ask_followup()` and fix message ordering.

- [ ] **Step 4: Commit**

```bash
git add tests/test_chat.py
git commit -m "test: add tool calling flow test for ask_followup"
```

---

### Task 6: `ask_followup()` — edge cases

**Files:**
- Modify: `chat.py` (if needed)
- Test: `tests/test_chat.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_chat.py`:

```python
def test_ask_followup_rejects_empty_question():
    """Verify ask_followup returns early on empty question."""
    from chat import ask_followup

    result = ask_followup(
        question="",
        ticker="AAPL",
        history=[],
        llm_url="http://localhost:8080/v1",
        model="qwen",
    )

    assert result["answer"] == ""
    assert result["history"] == []


def test_ask_followup_rejects_whitespace_question():
    """Verify ask_followup returns early on whitespace-only question."""
    from chat import ask_followup

    result = ask_followup(
        question="   ",
        ticker="AAPL",
        history=[],
        llm_url="http://localhost:8080/v1",
        model="qwen",
    )

    assert result["answer"] == ""


def test_ask_followup_handles_max_iterations():
    """Verify ask_followup stops after MAX_SEARCH_ITERATIONS tool calls."""
    from chat import ask_followup, MAX_SEARCH_ITERATIONS

    # LLM keeps requesting searches every time
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "web_search"
    mock_tool_call.function.arguments = '{"query": "test"}'

    mock_response = MagicMock()
    mock_response.choices[0].message.content = None
    mock_response.choices[0].message.tool_calls = [mock_tool_call]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("chat.OpenAI", return_value=mock_client):
        with patch("chat._web_search", return_value="Search results"):
            result = ask_followup(
                question="Test question",
                ticker="AAPL",
                history=[],
                llm_url="http://localhost:8080/v1",
                model="qwen",
            )

    # Should have been called exactly MAX_SEARCH_ITERATIONS times
    assert mock_client.chat.completions.create.call_count == MAX_SEARCH_ITERATIONS
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py::test_ask_followup_rejects_empty_question tests/test_chat.py::test_ask_followup_rejects_whitespace_question tests/test_chat.py::test_ask_followup_handles_max_iterations -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add chat.py tests/test_chat.py
git commit -m "test: add edge case tests for ask_followup"
```

---

### Task 7: Chat UI in `app.py`

**Files:**
- Modify: `app.py`

Add chat section to the Streamlit UI. This is a UI-only task — no tests needed (Streamlit UI is tested manually).

- [ ] **Step 1: Add chat session state initialization**

Add after existing session state initializations in `app.py` (after line with `_last_ticker`):

```python
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
```

- [ ] **Step 2: Reset chat history on new "Get News" run**

In `on_get_news()` function, add after the existing state resets:

```python
st.session_state.chat_history = []
```

- [ ] **Step 3: Add chat send callback**

Add before the Main Panel section in `app.py`:

```python
def on_chat_send():
    """Callback for chat send button — processes question and updates history."""
    question = st.session_state.get("chat_input", "").strip()
    if not question:
        return

    articles = st.session_state.articles or []
    custom_articles = st.session_state.custom_articles or []
    all_articles = articles + custom_articles
    summary = st.session_state.summary or None

    from chat import ask_followup

    result = ask_followup(
        question=question,
        ticker=ticker,
        history=st.session_state.chat_history,
        llm_url=llm_url,
        model=model,
        articles=all_articles if all_articles else None,
        summary=summary,
    )

    if result["answer"]:
        st.session_state.chat_history = result["history"]
        st.session_state.chat_input = ""
        st.rerun()
```

- [ ] **Step 4: Add chat UI section**

Add at the end of `app.py` (after all existing content):

```python
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

    # Chat input
    cols = st.columns([5, 1])
    with cols[0]:
        st.text_input(
            "Ask a follow-up question",
            key="chat_input",
            placeholder="e.g., What about regulatory risks? Summarize only earnings-related articles.",
            disabled=not ticker,
        )
    with cols[1]:
        st.button("Send", type="primary", use_container_width=True, on_click=on_chat_send)
else:
    st.info("Enter a ticker to start chatting.")
```

- [ ] **Step 5: Test the UI manually**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run streamlit run app.py`
Verify:
- Chat section appears at the bottom of the page
- "Ask about AAPL" shows when ticker is entered
- Sending a question shows user/assistant messages
- After "Get News", chat includes article context

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: add chat UI section to Streamlit app"
```

---

### Task 8: Run full test suite

**Files:**
- All files

- [ ] **Step 1: Run all tests**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest -v`
Expected: All tests pass (existing + new)

- [ ] **Step 2: Fix any failures**

If any existing tests break, fix them.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: follow-up chat with web search tool calling" || echo "nothing to commit"
```

---

## Self-Review Checklist

**Spec coverage:** All requirements covered.
- Multi-turn chat with conversation history → Task 4 (history management in `ask_followup`)
- Follow-up mode (with articles/summary) → Task 3 (system prompt builder), Task 7 (UI passes articles)
- Standalone mode (ticker only, web search) → Task 3 (standalone prompt), Task 4 (no articles required)
- Web search via SearXNG MCP → Task 1 (`_web_search`)
- Tool calling loop (max 3 iterations) → Task 4 (for loop with `MAX_SEARCH_ITERATIONS`)
- Chat UI in Streamlit → Task 7
- Session state management → Task 7 (chat_history init + reset)
- Error handling: LLM tool calling not supported → Task 4 (except block retries without tools)
- Error handling: web search fails → Task 2 (returns error string)
- Error handling: empty question → Task 6 (early return)
- Context trimming (last 10 turns) → Task 4 (`trimmed_history`)

**Placeholder scan:** No TBDs, TODOs, or vague instructions found.

**Type consistency:** `ask_followup` signature matches across all tasks. `_web_search` returns `str`. `_build_system_prompt` returns `str`. History is consistently `list[dict]` with `{role, content}` keys.
