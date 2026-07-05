# Follow-Up Chat — Design

## Overview

Add a multi-turn chat interface below the summaries section where users can ask follow-up questions about the scraped news. The LLM answers using the original articles, the initial summary, and conversation history — with the ability to search the web via MCP for additional context.

## Architecture

```
Streamlit UI (app.py)
├── scraper.py       Playwright → Yahoo Finance + custom URLs (unchanged)
├── summarizer.py    Single-shot LLM summarization (unchanged)
├── chat.py          NEW: Multi-turn chat + web search tool calling
└── presets.json     Preset definitions (unchanged)
```

`chat.py` is a new independent module with one public function. It handles the LLM tool-calling loop internally — the LLM may request web searches, the module executes them, feeds results back, and repeats. Returns the final answer and updated conversation history.

`app.py` adds a chat input below the summaries section, stores message history in `st.session_state`, and renders the conversation. No LLM logic leaks into the UI layer.

## Components

### `chat.py` — `ask_followup()`

```python
def ask_followup(
    question: str,
    articles: list[dict],      # scraped articles (Yahoo + custom)
    summary: str,              # initial summary from summarizer.py
    history: list[dict],       # prior chat messages [{role, content}, ...]
    llm_url: str,
    model: str,
) -> dict:
    # Returns {"answer": str, "history": list[dict]}
```

**Internal flow:**
1. Build system prompt with role ("financial analyst"), the ticker, the initial summary as reference, and all article titles + snippets
2. Append user's question to message history
3. Call LLM with `tools=[web_search_tool_definition]`
4. If LLM returns a tool call → execute web search via SearXNG MCP, inject result as `tool` role message, loop back to step 3 (max 3 search iterations)
5. If LLM returns text → append to history, return answer + updated history

**System prompt for chat:**
```
You are a financial news analyst helping a user understand news about {TICKER}.
You have access to the following context:

INITIAL SUMMARY:
{summary}

ARTICLES:
{articles_text}

Answer the user's question based on this context. If you need additional current information, use the web_search tool. Be concise and cite sources when referencing specific claims.
```

### Web search tool definition

Standard OpenAI function-calling schema passed to the LLM:

```json
{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information about a topic",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"}
            },
            "required": ["query"]
        }
    }
}
```

The tool implementation calls the SearXNG MCP (`mcp_web-search-mc_searxng_search`) and optionally `mcp_web-search-mc_web_scrape` for top results, returning formatted text snippets back to the LLM as a tool result message.

### `app.py` changes

Below the summaries section, add:
- **Chat header** — "💬 Ask a follow-up question" (only visible after summaries are ready)
- **Message list** — renders chat history from `st.session_state.chat_history` as alternating user/assistant messages
- **Text input** — single-line input at the bottom; sends to `ask_followup()` on Enter or button click
- **Loading state** — spinner while LLM is thinking/searching

**Session state additions:**
- `chat_history` — list of `{role, content}` dicts; reset on new "Get News" run
- `chat_thinking` — optional chain-of-thought from follow-up responses (collapsible expander)

### Context injection strategy

The system prompt includes:
- The **ticker** being discussed
- The **initial summary** as reference
- All **article titles + snippets** (not full article text, to stay within context window)

This gives the LLM enough to answer targeted questions without re-summarizing everything.

## Data Flow

```
User types question → app.py
    ↓
app.py calls chat.ask_followup(question, articles, summary, history, llm_url, model)
    ↓
chat.py builds system prompt + message list → OpenAI client call with tools=
    ↓ (if tool call)
LLM requests web_search("AAPL regulatory risks 2026")
    ↓
chat.py executes SearXNG search → formats results → injects as tool result message
    ↓ (loop back)
chat.py calls LLM again with tool result appended
    ↓ (if text response)
LLM returns answer → chat.py appends to history → returns {answer, history}
    ↓
app.py renders answer in chat UI, updates session_state.chat_history
```

## Error Handling

| Scenario | Behavior |
|---|---|
| LLM doesn't support tool calling | Catch `BadRequestError`/`NotFoundError` on first call, fall back to text-only response with note: "Web search unavailable — response based on scraped articles only" |
| Web search times out or fails | Inject error message as tool result ("Search failed: timeout"), let LLM decide how to proceed |
| Context window exceeded (long conversations) | Trim oldest assistant messages first, keep system prompt + last N turns; show warning if trimming aggressively |
| User sends empty question | Send button disabled for empty input |
| No articles/summary yet (user tries to chat before running Get News) | Chat section hidden until summaries are ready |

## Testing

**`test_chat.py`** — new test file:
- Mock LLM returning plain text → verify answer + history updated correctly
- Mock LLM returning tool call → verify search executed, result injected, second LLM call made
- Mock LLM returning multiple tool calls in one turn → verify all executed
- Tool call limit (3 iterations) → verify loop terminates gracefully
- Empty question → verify rejected early without LLM call
- LLM raises error on tool call → verify graceful fallback to text-only

**`test_summarizer.py`** — unchanged (existing tests still valid)
**`test_scraper.py`** — unchanged

## File Structure

```
bull_run/
├── app.py                  # add chat UI section + session state
├── chat.py                 # NEW: multi-turn chat + tool calling
├── scraper.py              # unchanged
├── summarizer.py           # unchanged
├── presets.json            # unchanged
├── pyproject.toml          # unchanged (no new dependencies)
└── tests/
    ├── test_chat.py        # NEW: chat unit tests
    ├── test_scraper.py     # unchanged
    ├── test_summarizer.py  # unchanged
    └── conftest.py         # unchanged
```

## Dependencies

No new runtime dependencies. The `openai` package already supports function/tool calling via the `tools=` parameter on `chat.completions.create()`. Web search uses the existing SearXNG MCP tools.
