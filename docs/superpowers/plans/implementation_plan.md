# Chat Module Improvement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix performance bottlenecks, output formatting bugs, architecture issues, and add real streaming support to the interactive chat implementation.

**Files Modified:**

| File | Action | Changes |
|---|---|---|
| `chat.py` | Modify | Centralize think stripping, truncate scrape content, remove function-attribute state, simplify search limits, parallelize tool calls, MCP reconnection, split into research + stream functions |
| `app.py` | Modify | `st.chat_message` containers, fix tool call display, integrate streaming, warm MCP |
| `summarizer.py` | Modify | Import centralized `strip_thinking_tags` from `chat.py` |
| `tests/test_chat.py` | Modify | Update mocks for new architecture, add new tests |

**Dependencies between tasks:** Tasks 1–4 are independent internal refactors. Task 5 depends on Task 4 (simplified loop). Tasks 8–9 depend on Tasks 1–7 (clean `chat.py` API). Task 10–11 depend on Task 8. Task 12 should run last.

---

## Phase 1: Internal Cleanup (`chat.py`)

### Task 1: Centralize thinking-tag stripping

**Files:**
- Modify: `chat.py`
- Modify: `app.py`
- Modify: `summarizer.py`
- Test: `tests/test_chat.py`

Add a single `strip_thinking_tags()` function in `chat.py` and use it everywhere instead of duplicating regex logic.

- [ ] **Step 1: Add `strip_thinking_tags` function to `chat.py`**

Add this function after `_strip_tool_call_xml` (after line 34 of `chat.py`):

```python
def strip_thinking_tags(text: str) -> tuple[str, str]:
    """Extract and strip chain-of-thought tags from LLM output.

    Handles <think>...</think>, <thinking>...</thinking>, and trailing
    unclosed <think> blocks.

    Args:
        text: Raw LLM output text.

    Returns:
        Tuple of (cleaned_text, thinking_content). thinking_content is empty
        string if no thinking tags found.
    """
    # Extract thinking content
    thinking_parts = re.findall(r'<think>(.*?)</think>', text, flags=re.DOTALL | re.IGNORECASE)
    thinking_parts += re.findall(r'<thinking>(.*?)</thinking>', text, flags=re.DOTALL | re.IGNORECASE)
    # Catch trailing incomplete thinking fragments
    thinking_parts += re.findall(r'<think>(.*?)$', text, flags=re.DOTALL | re.IGNORECASE)

    thinking = "\n".join(p.strip() for p in thinking_parts if p.strip())

    # Strip all thinking blocks from the text
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<thinking>.*?</thinking>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'\s*<think>.*$', '', cleaned, flags=re.DOTALL | re.IGNORECASE)

    return cleaned.strip(), thinking
```

- [ ] **Step 2: Use `strip_thinking_tags` in `ask_followup` (chat.py)**

At line 510 in `chat.py`, replace:

```python
        answer = _strip_tool_call_xml(message.content or "")
```

with:

```python
        raw_answer = message.content or ""
        answer, _ = strip_thinking_tags(raw_answer)
        answer = _strip_tool_call_xml(answer)
```

At line 537, replace:

```python
        answer = _strip_tool_call_xml(final_response.choices[0].message.content or "Search limit reached.")
```

with:

```python
        raw_answer = final_response.choices[0].message.content or "Search limit reached."
        answer, _ = strip_thinking_tags(raw_answer)
        answer = _strip_tool_call_xml(answer)
```

- [ ] **Step 3: Replace inline regex in `app.py`**

In `app.py`, replace the entire thinking-tag stripping block (lines 512–525):

```python
        # Strip thinking tags from answer
        full_answer = result["answer"] or ""
        thinking = ""
        # Extract thinking content before stripping
        for pattern in [r'<think>(.*?)</think>', r'<thinking>(.*?)</thinking>']:
            matches = re.findall(pattern, full_answer, re.DOTALL | re.IGNORECASE)
            if matches:
                thinking = "\n".join(m.strip() for m in matches).strip()
                break
        # Clean answer — strip thinking tags
        full_answer = re.sub(r'<think>.*?</think>', '', full_answer, flags=re.DOTALL | re.IGNORECASE)
        full_answer = re.sub(r'<thinking>.*?</thinking>', '', full_answer, flags=re.DOTALL | re.IGNORECASE)
        full_answer = re.sub(r'\s*<think>.*$', '', full_answer, flags=re.DOTALL | re.IGNORECASE)
        full_answer = full_answer.strip()
```

with:

```python
        # Strip thinking tags from answer (uses centralized function from chat.py)
        from chat import strip_thinking_tags
        full_answer = result["answer"] or ""
        full_answer, thinking = strip_thinking_tags(full_answer)
```

Also remove the `import re` at line 477 since it's no longer needed in this block.

- [ ] **Step 4: Update `summarizer.py` to use the shared function**

In `summarizer.py`, replace the inline thinking-tag stripping code (lines 50–61):

```python
    # Extract chain-of-thought blocks before stripping them
    thinking_parts = re.findall(r'<think>(.*?)</think>', content, flags=re.DOTALL | re.IGNORECASE)
    thinking_parts += re.findall(r'<thinking>(.*?)</thinking>', content, flags=re.DOTALL | re.IGNORECASE)
    # Also catch trailing incomplete thinking fragments
    trailing = re.findall(r'<think>(.*?)$', content, flags=re.DOTALL | re.IGNORECASE)
    thinking_parts += trailing

    thinking = "\n".join(p.strip() for p in thinking_parts if p.strip())

    # Strip all chain-of-thought blocks from the summary
    summary = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL | re.IGNORECASE)
    summary = re.sub(r'<thinking>.*?</thinking>', '', summary, flags=re.DOTALL | re.IGNORECASE)
    summary = re.sub(r'\s*<think>.*$', '', summary, flags=re.DOTALL | re.IGNORECASE)
```

with:

```python
    from chat import strip_thinking_tags
    summary, thinking = strip_thinking_tags(content)
```

The `import re` at the top of `summarizer.py` can be removed since it's no longer used directly.

- [ ] **Step 5: Run tests**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/ -v`
Expected: All existing tests pass (function is additive; `ask_followup` now strips thinking internally but the test mocks don't include thinking tags so the behavior is unchanged).

- [ ] **Step 6: Commit**

```bash
git add chat.py app.py summarizer.py
git commit -m "refactor: centralize thinking-tag stripping into chat.strip_thinking_tags()"
```

---

### Task 2: Truncate scraped content

**Files:**
- Modify: `chat.py`
- Test: `tests/test_chat.py`

Scraped content can be up to 8000+ chars. With 3 scrapes that's ~24K chars of raw page text in the context, slowing local LLM inference. Truncate to 4000 chars per scrape to cut context by ~50%.

- [ ] **Step 1: Add constant and truncation**

In `chat.py`, after line 40 (`MAX_PARALLEL_SEARCHES = 2`), add:

```python
MAX_SCRAPE_CONTENT_LENGTH = 4000  # Truncate scraped page content to limit context size
```

In the `_web_scrape` function (line 212–222), change it to:

```python
def _web_scrape(url: str) -> str:
    """Scrape a URL via MCP server's web_scrape tool (uses Playwright).

    Args:
        url: The URL to scrape.

    Returns:
        Text content from the page, truncated to MAX_SCRAPE_CONTENT_LENGTH.
    """
    mcp = _MCPClient.get()
    result = mcp.call_tool("web_scrape", {"url": url})
    if len(result) > MAX_SCRAPE_CONTENT_LENGTH:
        result = result[:MAX_SCRAPE_CONTENT_LENGTH] + "\n\n[Content truncated — showing first ~4000 characters]"
    return result
```

- [ ] **Step 2: Run tests**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py -v`
Expected: All pass — the mock returns short strings so truncation doesn't trigger.

- [ ] **Step 3: Commit**

```bash
git add chat.py
git commit -m "perf: truncate scraped content to 4000 chars to reduce context size"
```

---

### Task 3: Remove function-attribute state

**Files:**
- Modify: `chat.py`

Replace `ask_followup._tool_calls` (a mutable attribute on the function object) with a local variable. The function attribute is not thread-safe and redundant with the return value.

- [ ] **Step 1: Replace function attribute with local variable**

In `ask_followup` (chat.py), make these changes:

At line 343–344, replace:

```python
    # Reset tool calls tracking for this invocation
    ask_followup._tool_calls = []
```

with:

```python
    # Track tool calls for this invocation
    tool_calls_list = []
```

At lines 479–482, replace:

```python
            # Store tool call info for this iteration
            if not hasattr(ask_followup, "_tool_calls"):
                ask_followup._tool_calls = []
            ask_followup._tool_calls.extend(tool_call_info)
```

with:

```python
            # Store tool call info for this iteration
            tool_calls_list.extend(tool_call_info)
```

At line 518, replace:

```python
            "tool_calls": ask_followup._tool_calls,
```

with:

```python
            "tool_calls": tool_calls_list,
```

At line 548, replace:

```python
        "tool_calls": ask_followup._tool_calls,
```

with:

```python
        "tool_calls": tool_calls_list,
```

Also at line 388 (the error return inside the except block), replace:

```python
                return {"answer": error_answer, "history": new_history, "tool_calls": ask_followup._tool_calls}
```

with:

```python
                return {"answer": error_answer, "history": new_history, "tool_calls": tool_calls_list}
```

- [ ] **Step 2: Run tests**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py -v`
Expected: All 12 pass.

- [ ] **Step 3: Commit**

```bash
git add chat.py
git commit -m "refactor: replace function-attribute _tool_calls with local variable"
```

---

### Task 4: Simplify search limiting

**Files:**
- Modify: `chat.py`

Remove the `searches_done` flag and the fake user message injection. Keep only `MAX_SEARCHES` (global cap) + `MAX_PARALLEL_SEARCHES` (per-turn cap) — these two are sufficient and the system prompt already instructs the LLM to stop after 2 searches.

- [ ] **Step 1: Remove `searches_done` flag**

In `ask_followup`, at line 348, delete:

```python
    searches_done = [False]  # After first iteration with searches, block further searches
```

- [ ] **Step 2: Remove `searches_done` blocking in tool execution**

In the tool execution block (around lines 422–432), remove the `searches_done` check. Replace the full `if name == "searxng_search":` block (lines 423–451) with:

```python
                if name == "searxng_search":
                    turn_search_count[0] += 1
                    if turn_search_count[0] > MAX_PARALLEL_SEARCHES:
                        tool_name = "searxng_search"
                        result = (
                            f"Parallel search limit reached ({MAX_PARALLEL_SEARCHES} per turn). "
                            "Process the results you already have — use web_scrape on the URLs found."
                        )
                        blocked = True
                    elif search_count[0] >= MAX_SEARCHES:
                        tool_name = "searxng_search"
                        result = (
                            f"Search limit reached ({MAX_SEARCHES}/{MAX_SEARCHES}). "
                            "STOP searching. Use web_scrape to read the full content of URLs from your previous "
                            "search results instead. Do not issue any more searxng_search calls."
                        )
                        blocked = True
                    else:
                        search_count[0] += 1
                        tool_name, result = ("searxng_search", _web_search(args.get("query", "").strip()))
```

- [ ] **Step 3: Remove `searches_done` assignment and corrective reminder injection**

Remove lines 484–505 entirely (the `searches_done[0] = True` assignment and the corrective reminder block):

```python
            # After the first iteration with searches, lock searches so subsequent
            # iterations can only scrape or answer.
            if search_count[0] > 0:
                searches_done[0] = True

            # Enforce search -> scrape pattern: if this iteration was all searches and we've
            # already done searches before, inject a corrective reminder forcing web_scrape.
            tool_names_this_iter = [d["tool"] for d in tool_call_info]
            if (
                all(t == "searxng_search" for t in tool_names_this_iter)
                and search_count[0] >= 2
            ):
                reminder = (
                    "\u26a0 REMINDER: You already have search results with URLs. "
                    "STOP searching and use web_scrape to read the full content of at least "
                    "2-3 of the most relevant URLs from your search results. "
                    "Do not issue any more searxng_search calls until you have scraped content."
                )
                messages.append({
                    "role": "user",
                    "content": reminder,
                })
```

Replace with just:

```python
            # (No additional limiting — MAX_SEARCHES + MAX_PARALLEL_SEARCHES + system prompt is sufficient)
```

- [ ] **Step 4: Also remove the now-redundant `_execute_tool_call` function**

The `_execute_tool_call` function (lines 281–313) is only called for non-search tools inside the tool execution loop. Its search-handling logic is dead code because searches are handled inline. Simplify by removing the search logic from `_execute_tool_call`:

Replace the entire `_execute_tool_call` function with:

```python
def _execute_tool_call(tool_call) -> tuple[str, str]:
    """Execute an LLM tool call and return (tool_name, result_text).

    Args:
        tool_call: The tool call object from the LLM response.

    Returns:
        Tuple of (tool_name, result_text).
    """
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)

    if name == "searxng_search":
        query = args.get("query", "").strip()
        if not query:
            return ("searxng_search", "Error: query parameter is required and cannot be empty.")
        return ("searxng_search", _web_search(query))
    elif name == "web_scrape":
        url = args.get("url", "").strip()
        if not url:
            return ("web_scrape", "Error: url parameter is required and cannot be empty.")
        return ("web_scrape", _web_scrape(url))
    else:
        return (name, f"Unknown tool: {name}")
```

Update the call site at line 453 — change:

```python
                    tool_name, result = _execute_tool_call(tool_call, search_count)
```

to:

```python
                    tool_name, result = _execute_tool_call(tool_call)
```

- [ ] **Step 5: Change the "max iterations" forced-answer message**

At lines 521–529, change the fake user message role from `"user"` to `"system"`:

```python
    messages.append({
        "role": "system",
        "content": (
            "Please provide your final answer now based on the research results above. "
            "Do not make any more tool calls — just write your answer."
        ),
    })
```

- [ ] **Step 6: Run tests**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py -v`
Expected: All pass. The `test_ask_followup_handles_max_iterations` test should still pass because `MAX_SEARCH_ITERATIONS` loop count is unchanged.

- [ ] **Step 7: Commit**

```bash
git add chat.py
git commit -m "refactor: simplify search limiting — remove searches_done flag and fake user messages"
```

---

## Phase 2: Performance (`chat.py`)

### Task 5: Parallelize tool calls

**Files:**
- Modify: `chat.py`
- Test: `tests/test_chat.py`

When the LLM requests multiple tool calls in one turn (e.g., 2 web_scrape calls), they're executed sequentially. Use `concurrent.futures.ThreadPoolExecutor` to run them in parallel, saving 10–30s per multi-scrape turn.

- [ ] **Step 1: Add import**

At the top of `chat.py`, add to imports (after line 3):

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
```

- [ ] **Step 2: Refactor tool execution block to use ThreadPoolExecutor**

In `ask_followup`, replace the sequential tool execution block. The current block that starts with `turn_search_count = [0]` and iterates over `message.tool_calls` (approximately lines 416–477) should be replaced with:

```python
            # Execute tool calls (parallel where possible, with search limiting)
            turn_search_count = 0
            tool_results = {}  # tool_call.id -> (tool_name, result, args, blocked)

            def _safe_execute(tc):
                """Execute a single tool call, returning (tool_call_id, tool_name, result, args, blocked)."""
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                return (tc.id, name, *_execute_tool_call(tc), args, False)

            # Separate searches (rate-limited) from scrapes (parallelizable)
            search_calls = []
            other_calls = []
            for tc in message.tool_calls:
                if tc.function.name == "searxng_search":
                    search_calls.append(tc)
                else:
                    other_calls.append(tc)

            # Execute searches sequentially (to enforce limits)
            for tc in search_calls:
                args = json.loads(tc.function.arguments)
                turn_search_count += 1
                if turn_search_count > MAX_PARALLEL_SEARCHES:
                    tool_results[tc.id] = (
                        "searxng_search",
                        f"Parallel search limit reached ({MAX_PARALLEL_SEARCHES} per turn). "
                        "Process the results you already have — use web_scrape on the URLs found.",
                        args,
                        True,  # blocked
                    )
                elif search_count[0] >= MAX_SEARCHES:
                    tool_results[tc.id] = (
                        "searxng_search",
                        f"Search limit reached ({MAX_SEARCHES}/{MAX_SEARCHES}). "
                        "STOP searching. Use web_scrape to read the full content of URLs from your previous "
                        "search results instead.",
                        args,
                        True,  # blocked
                    )
                else:
                    search_count[0] += 1
                    tool_results[tc.id] = (
                        "searxng_search",
                        _web_search(args.get("query", "").strip()),
                        args,
                        False,
                    )

            # Execute scrapes and other tools in parallel
            if other_calls:
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_tc = {
                        executor.submit(_execute_tool_call, tc): tc
                        for tc in other_calls
                    }
                    for future in as_completed(future_to_tc):
                        tc = future_to_tc[future]
                        args = json.loads(tc.function.arguments)
                        try:
                            tool_name, result = future.result()
                        except Exception as e:
                            tool_name = tc.function.name
                            result = f"Tool execution failed: {e}"
                        tool_results[tc.id] = (tool_name, result, args, False)

            # Build tool call display info and append tool result messages (in original order)
            for tc in message.tool_calls:
                tool_name, result, args, blocked = tool_results[tc.id]

                if not blocked:
                    if tool_name == "searxng_search":
                        display = {
                            "tool": "searxng_search",
                            "query": args.get("query", ""),
                            "result": result,
                        }
                    elif tool_name == "web_scrape":
                        display = {
                            "tool": "web_scrape",
                            "url": args.get("url", ""),
                            "result": result,
                        }
                    else:
                        display = {"tool": tool_name, "result": result}
                    tool_call_info.append(display)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
```

- [ ] **Step 3: Run tests**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add chat.py
git commit -m "perf: parallelize web_scrape tool calls with ThreadPoolExecutor"
```

---

### Task 6: Add MCP reconnection

**Files:**
- Modify: `chat.py`

If the MCP subprocess crashes, the singleton is permanently broken. Add a `reset()` method to `_MCPClient` that destroys and recreates the connection.

- [ ] **Step 1: Add `reset()` classmethod**

In the `_MCPClient` class, after the `is_available` property (after line 160), add:

```python
    @classmethod
    def reset(cls):
        """Destroy the current instance and allow a fresh connection on next .get() call."""
        instance = cls._state.get("_instance")
        if instance is not None:
            # Stop the event loop if running
            if instance._loop is not None and instance._loop.is_running():
                instance._loop.call_soon_threadsafe(instance._loop.stop)
            # Wait for thread to finish
            if instance._thread is not None and instance._thread.is_alive():
                instance._thread.join(timeout=5)
        cls._state["_instance"] = None
        logger.info("MCP client reset — will reconnect on next use.")
```

- [ ] **Step 2: Add auto-reconnection in `call_tool`**

In the `call_tool` method, replace the `is_available` check (lines 171–172):

```python
        if not self.is_available:
            return "MCP server is not available."
```

with:

```python
        if not self.is_available:
            logger.warning("MCP server not available — attempting reconnection...")
            _MCPClient.reset()
            try:
                new_instance = _MCPClient()
                _MCPClient._state["_instance"] = new_instance
                if not new_instance._ready_event.wait(timeout=15):
                    return "MCP server reconnection timed out."
                if not new_instance.is_available:
                    return "MCP server reconnection failed."
                # Retry the tool call on the new instance
                return new_instance.call_tool(tool_name, arguments)
            except Exception as e:
                logger.exception("MCP server reconnection failed")
                return f"MCP server reconnection failed: {e}"
```

> [!WARNING]
> This auto-reconnection adds a recursive `call_tool` call. The recursion is bounded (depth 1) because the new instance will have `is_available = True` after successful reconnection, so it won't recurse again. If the new instance also fails, the `is_available` check returns the error string directly.

- [ ] **Step 3: Run tests**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py -v`
Expected: All pass (tests mock `_MCPClient.get()` so reconnection logic is not exercised).

- [ ] **Step 4: Commit**

```bash
git add chat.py
git commit -m "feat: add MCP auto-reconnection on subprocess failure"
```

---

### Task 7: Warm-start MCP server

**Files:**
- Modify: `chat.py`
- Modify: `app.py`

The first chat question incurs a 10–15s cold-start penalty while the MCP server initializes. Pre-warm it when the app loads.

- [ ] **Step 1: Add `warm()` function to `chat.py`**

At the end of `chat.py` (after all existing code), add:

```python
def warm_mcp():
    """Pre-initialize the MCP server connection.

    Call this at app startup to avoid cold-start delay on the first chat question.
    Non-blocking — the server starts in a background thread.
    """
    try:
        _MCPClient.get()
        logger.info("MCP server warm-start initiated.")
    except Exception:
        logger.warning("MCP server warm-start failed — will retry on first use.")
```

- [ ] **Step 2: Call `warm_mcp()` in `app.py` at startup**

In `app.py`, after the session state initialization block (after line 85), add:

```python
# --- Warm MCP server for chat (non-blocking background init) ---
if "mcp_warmed" not in st.session_state:
    from chat import warm_mcp
    warm_mcp()
    st.session_state.mcp_warmed = True
```

- [ ] **Step 3: Run tests**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/ -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add chat.py app.py
git commit -m "perf: warm-start MCP server at app load to avoid cold-start delay"
```

---

## Phase 3: Refactor for Streaming (`chat.py` API)

### Task 8: Split `ask_followup` into research + streaming functions

**Files:**
- Modify: `chat.py`
- Test: `tests/test_chat.py`

Split the monolithic `ask_followup` into:
1. `_run_tool_loop()` — runs tool-calling iterations synchronously, returns accumulated messages + tool call metadata
2. `stream_final_answer()` — streaming generator for the final LLM answer
3. `ask_followup()` — backward-compatible wrapper that calls both

This enables the UI to show research progress in `st.status` and stream the final answer with `st.write_stream`.

- [ ] **Step 1: Create `_run_tool_loop` function**

Add this new function in `chat.py`, **before** the existing `ask_followup` function. This extracts the tool-calling loop from `ask_followup`:

```python
def _run_tool_loop(
    question: str,
    ticker: str,
    history: list[dict],
    llm_url: str,
    model: str,
    articles: Optional[list[dict]] = None,
    summary: Optional[str] = None,
) -> dict:
    """Run the tool-calling loop synchronously.

    Executes LLM calls with tool calling until the model either:
    - Returns a text answer (no tool calls), or
    - Exceeds MAX_SEARCH_ITERATIONS

    Args:
        question: User's question.
        ticker: Stock ticker symbol.
        history: Prior chat messages [{role, content}, ...].
        llm_url: OpenAI-compatible LLM base URL.
        model: Model name.
        articles: Optional scraped articles for context.
        summary: Optional initial summary for context.

    Returns:
        Dict with:
        - 'messages': Full message list (for a follow-up streaming call if needed)
        - 'tool_calls': List of {tool, query/url, result} dicts for UI display
        - 'trimmed_history': Trimmed conversation history
        - 'answer': The text answer if the LLM returned one, or None
        - 'needs_final_call': True if the loop exhausted without a text answer
    """
    tool_calls_list = []
    search_count = [0]

    client = OpenAI(base_url=llm_url, api_key="not-needed", timeout=120.0)
    system_prompt = _build_system_prompt(ticker, articles, summary)

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    trimmed_history = history[-(MAX_CHAT_TURNS * 2):] if len(history) > MAX_CHAT_TURNS * 2 else history
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": question})

    for iteration in range(MAX_SEARCH_ITERATIONS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                temperature=0.1,
                max_tokens=4096,
            )
        except Exception as e:
            logger.exception("LLM call failed, falling back to text-only")
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=4096,
                )
            except Exception as e2:
                return {
                    "messages": messages,
                    "tool_calls": tool_calls_list,
                    "trimmed_history": trimmed_history,
                    "answer": f"LLM error: {e2}",
                    "needs_final_call": False,
                }

        message = response.choices[0].message

        if message.tool_calls:
            tool_call_info = []

            assistant_msg = {
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
            }
            if message.content:
                assistant_msg["content"] = message.content
            messages.append(assistant_msg)

            # --- Parallel tool execution (same logic as Task 5) ---
            turn_search_count = 0
            tool_results = {}

            search_calls = [tc for tc in message.tool_calls if tc.function.name == "searxng_search"]
            other_calls = [tc for tc in message.tool_calls if tc.function.name != "searxng_search"]

            for tc in search_calls:
                args = json.loads(tc.function.arguments)
                turn_search_count += 1
                if turn_search_count > MAX_PARALLEL_SEARCHES:
                    tool_results[tc.id] = ("searxng_search",
                        f"Parallel search limit reached ({MAX_PARALLEL_SEARCHES} per turn). "
                        "Process the results you already have — use web_scrape on the URLs found.",
                        args, True)
                elif search_count[0] >= MAX_SEARCHES:
                    tool_results[tc.id] = ("searxng_search",
                        f"Search limit reached ({MAX_SEARCHES}/{MAX_SEARCHES}). "
                        "STOP searching. Use web_scrape on URLs from previous search results.",
                        args, True)
                else:
                    search_count[0] += 1
                    tool_results[tc.id] = ("searxng_search",
                        _web_search(args.get("query", "").strip()),
                        args, False)

            if other_calls:
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_tc = {
                        executor.submit(_execute_tool_call, tc): tc
                        for tc in other_calls
                    }
                    for future in as_completed(future_to_tc):
                        tc = future_to_tc[future]
                        args = json.loads(tc.function.arguments)
                        try:
                            tool_name, result = future.result()
                        except Exception as e:
                            tool_name = tc.function.name
                            result = f"Tool execution failed: {e}"
                        tool_results[tc.id] = (tool_name, result, args, False)

            for tc in message.tool_calls:
                tool_name, result, args, blocked = tool_results[tc.id]
                if not blocked:
                    if tool_name == "searxng_search":
                        display = {"tool": "searxng_search", "query": args.get("query", ""), "result": result}
                    elif tool_name == "web_scrape":
                        display = {"tool": "web_scrape", "url": args.get("url", ""), "result": result}
                    else:
                        display = {"tool": tool_name, "result": result}
                    tool_call_info.append(display)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            tool_calls_list.extend(tool_call_info)
            continue

        # Text response — done
        raw_answer = message.content or ""
        answer, _ = strip_thinking_tags(raw_answer)
        answer = _strip_tool_call_xml(answer)
        return {
            "messages": messages,
            "tool_calls": tool_calls_list,
            "trimmed_history": trimmed_history,
            "answer": answer,
            "needs_final_call": False,
        }

    # Exceeded max iterations — need a final call to get the answer
    messages.append({
        "role": "system",
        "content": (
            "Please provide your final answer now based on the research results above. "
            "Do not make any more tool calls — just write your answer."
        ),
    })
    return {
        "messages": messages,
        "tool_calls": tool_calls_list,
        "trimmed_history": trimmed_history,
        "answer": None,
        "needs_final_call": True,
    }
```

- [ ] **Step 2: Create `stream_final_answer` function**

Add this new function after `_run_tool_loop`:

```python
def stream_final_answer(messages: list[dict], llm_url: str, model: str):
    """Generator that yields text chunks from a streaming LLM call.

    Used after _run_tool_loop when the loop exhausted its iterations and
    needs a final answer from the LLM.

    Args:
        messages: Full message history (including system prompt + tool results).
        llm_url: OpenAI-compatible LLM base URL.
        model: Model name.

    Yields:
        Text chunks (strings) as they arrive from the LLM.
    """
    client = OpenAI(base_url=llm_url, api_key="not-needed", timeout=120.0)
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=4096,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
    except Exception as e:
        logger.exception("Streaming LLM call failed")
        yield f"LLM error: {e}"
```

- [ ] **Step 3: Rewrite `ask_followup` as a thin wrapper**

Replace the entire current `ask_followup` function with this backward-compatible wrapper:

```python
def ask_followup(
    question: str,
    ticker: str,
    history: list[dict],
    llm_url: str,
    model: str,
    articles: Optional[list[dict]] = None,
    summary: Optional[str] = None,
) -> dict:
    """Process a follow-up question with multi-turn chat and MCP tool calling.

    Backward-compatible synchronous wrapper around _run_tool_loop + stream_final_answer.

    Args:
        question: User's question.
        ticker: Stock ticker symbol.
        history: Prior chat messages [{role, content}, ...].
        llm_url: OpenAI-compatible LLM base URL.
        model: Model name.
        articles: Optional scraped articles for context.
        summary: Optional initial summary for context.

    Returns:
        Dict with 'answer' (LLM response text), 'history' (updated message list),
        and 'tool_calls' (list of {tool, query, result} dicts for UI display).
    """
    if not question.strip():
        return {"answer": "", "history": history, "tool_calls": []}

    result = _run_tool_loop(question, ticker, history, llm_url, model, articles, summary)

    if result["needs_final_call"]:
        # Collect streaming chunks into a single string
        chunks = list(stream_final_answer(result["messages"], llm_url, model))
        raw_answer = "".join(chunks)
        answer, _ = strip_thinking_tags(raw_answer)
        answer = _strip_tool_call_xml(answer)
        if not answer:
            answer = "Search limit reached. I'll provide my best answer with the information I have."
    else:
        answer = result["answer"]

    trimmed = result["trimmed_history"]
    new_history = trimmed + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]
    return {"answer": answer, "history": new_history, "tool_calls": result["tool_calls"]}
```

- [ ] **Step 4: Delete `chat.py.bak`**

The old streaming attempt is now superseded. Remove it:

```bash
rm chat.py.bak
```

- [ ] **Step 5: Run tests**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/test_chat.py -v`
Expected: All 12 pass — `ask_followup` signature and return shape are unchanged.

- [ ] **Step 6: Commit**

```bash
git add chat.py
git rm chat.py.bak
git commit -m "refactor: split ask_followup into _run_tool_loop + stream_final_answer"
```

---

## Phase 4: UI Overhaul (`app.py`)

### Task 9: Fix chat history rendering with `st.chat_message`

**Files:**
- Modify: `app.py`

Replace manual `st.markdown(f"**You:** {msg['content']}")` with Streamlit's native `st.chat_message()` containers. This fixes the formatting bug where structured assistant responses (headings, lists) broke when inlined with the "**Assistant:**" label.

- [ ] **Step 1: Add `chat_thinking` to session state**

Add after the `chat_pending` init (after line 85):

```python
if "chat_thinking" not in st.session_state:
    st.session_state.chat_thinking = {}  # Maps message index -> thinking content
```

Also add a reset in `on_get_news()` (after line 226):

```python
    st.session_state.chat_thinking = {}
```

- [ ] **Step 2: Replace the chat history rendering block**

Replace lines 468–473:

```python
    # Render chat history
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f"**You:** {msg['content']}")
        elif msg["role"] == "assistant":
            st.markdown(f"**Assistant:** {msg['content']}")
```

with:

```python
    # Render chat history using native chat containers
    for i, msg in enumerate(st.session_state.chat_history):
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        elif msg["role"] == "assistant":
            with st.chat_message("assistant"):
                st.markdown(msg["content"])
                # Show thinking if we stored it for this message
                thinking = st.session_state.chat_thinking.get(i, "")
                if thinking:
                    with st.expander("🧠 Model's Reasoning Process"):
                        st.markdown(thinking)
```

- [ ] **Step 3: Update the pending question display**

Replace lines 482–483:

```python
        # Show user's question immediately
        st.markdown(f"**You:** {pending['question']}")
```

with:

```python
        # Show user's question immediately
        with st.chat_message("user"):
            st.markdown(pending["question"])
```

Replace lines 527–530 (the answer rendering):

```python
        # Render answer as proper markdown
        st.markdown("**Assistant:**")
        if full_answer:
            st.markdown(full_answer)
```

with:

```python
        # Render answer using native chat container
        with st.chat_message("assistant"):
            if full_answer:
                st.markdown(full_answer)
```

Move the thinking expander inside the `st.chat_message("assistant")` block (it should appear inside the assistant bubble):

```python
        with st.chat_message("assistant"):
            if full_answer:
                st.markdown(full_answer)
            if thinking:
                with st.expander("🧠 Model's Reasoning Process"):
                    st.markdown(thinking)
```

- [ ] **Step 4: Store thinking content for history rendering**

After the history save (around line 538), add thinking storage:

```python
        # Save thinking content keyed by assistant message index
        if thinking:
            assistant_idx = len(st.session_state.chat_history) - 1
            st.session_state.chat_thinking[assistant_idx] = thinking
```

- [ ] **Step 5: Replace `st.text_input` with `st.chat_input`**

Replace lines 554–562:

```python
    # Chat input (Enter to send)
    is_chatting = st.session_state.chat_pending is not None
    st.text_input(
        "Ask a follow-up question",
        key="chat_input",
        placeholder="e.g., What about regulatory risks? Summarize only earnings-related articles.",
        disabled=not ticker or is_chatting,
        on_change=on_chat_send,
    )
```

with:

```python
    # Chat input
    if prompt := st.chat_input(
        "Ask a follow-up question...",
        disabled=not ticker or st.session_state.chat_pending is not None,
    ):
        st.session_state.chat_input = prompt
        on_chat_send()
```

Update `on_chat_send()` to read from the new source. In the `on_chat_send` function, change:

```python
    question = st.session_state.get("chat_input", "").strip()
```

to:

```python
    question = st.session_state.get("chat_input", "").strip()
```

This is unchanged — `st.chat_input` doesn't use a key, so we manually set `chat_input` in session state before calling the callback. The `st.session_state.chat_input = ""` reset at line 356 should be kept.

- [ ] **Step 6: Run the app manually**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run streamlit run app.py`

Verify:
- Chat messages render in proper chat bubbles (user on right, assistant on left)
- Multi-line assistant responses (headings, bullet lists) render correctly
- Thinking expanders appear inside assistant message bubbles
- Chat input appears at the bottom with proper styling

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: switch chat UI to st.chat_message containers for proper formatting"
```

---

### Task 10: Fix tool call display

**Files:**
- Modify: `app.py`

The "Tool Calls Made" expander hardcodes "web_search" for all tools and ignores the `url` field for scrape calls.

- [ ] **Step 1: Fix the tool calls expander**

Replace lines 544–552:

```python
    # Render tool calls from last response (if any, and not currently streaming)
    elif st.session_state.chat_tool_calls:
        with st.expander("🔧 Tool Calls Made", expanded=False):
            for i, tc in enumerate(st.session_state.chat_tool_calls, 1):
                st.markdown(f"**{i}. web_search** — `{tc.get('query', '')}`")
                tc_result = tc.get("result", "")
                if tc_result:
                    with st.expander("Result"):
                        st.markdown(tc_result)
```

with:

```python
    # Render tool calls from last response (if any, and not currently streaming)
    elif st.session_state.chat_tool_calls:
        with st.expander("🔧 Tool Calls Made", expanded=False):
            for i, tc in enumerate(st.session_state.chat_tool_calls, 1):
                tool = tc.get("tool", "unknown")
                if tool == "searxng_search":
                    st.markdown(f"**{i}. 🔎 web_search** — `{tc.get('query', '')}`")
                elif tool == "web_scrape":
                    url = tc.get("url", "")
                    display_url = url[:80] + "..." if len(url) > 80 else url
                    st.markdown(f"**{i}. 📄 web_scrape** — `{display_url}`")
                else:
                    st.markdown(f"**{i}. {tool}**")
                tc_result = tc.get("result", "")
                if tc_result:
                    with st.expander(f"Result ({tool})"):
                        st.text(tc_result[:2000])  # Cap display length
```

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "fix: correct tool call display labels for web_scrape and other tools"
```

---

### Task 11: Integrate streaming into the chat UI

**Files:**
- Modify: `app.py`

Use `_run_tool_loop` + `stream_final_answer` from `chat.py` to show real-time research progress and stream the final answer.

- [ ] **Step 1: Replace the pending question processing block**

Replace the entire `if st.session_state.chat_pending:` block (approximately lines 475–542) with:

```python
    # Process pending question with research + streaming
    if st.session_state.chat_pending:
        from chat import _run_tool_loop, stream_final_answer, strip_thinking_tags, _strip_tool_call_xml

        pending = st.session_state.chat_pending

        # Show user's question
        with st.chat_message("user"):
            st.markdown(pending["question"])

        # Phase 1: Research (tool-calling loop with live status)
        with st.status("🔍 Researching...", expanded=True) as status:
            research = _run_tool_loop(
                question=pending["question"],
                ticker=pending["ticker"],
                history=pending["history"],
                llm_url=pending["llm_url"],
                model=pending["model"],
                articles=pending["articles"],
                summary=pending["summary"],
            )

            # Show tool calls made during research
            if research["tool_calls"]:
                for i, tc in enumerate(research["tool_calls"], 1):
                    tool = tc.get("tool", "unknown")
                    if tool == "searxng_search":
                        status.markdown(f"{i}. 🔎 web_search — `{tc.get('query', '')}`")
                    elif tool == "web_scrape":
                        url = tc.get("url", "")
                        display_url = url[:80] + "..." if len(url) > 80 else url
                        status.markdown(f"{i}. 📄 web_scrape — `{display_url}`")
                    else:
                        status.markdown(f"{i}. {tool}")

            if research["needs_final_call"]:
                status.update(label="✍️ Writing answer...", state="running")
            else:
                status.update(label="✅ Research complete", state="complete")

        st.session_state.chat_tool_calls = research["tool_calls"]

        # Phase 2: Generate answer
        with st.chat_message("assistant"):
            if research["needs_final_call"]:
                # Stream the final answer
                answer_placeholder = st.empty()
                raw_chunks = []
                for chunk in stream_final_answer(
                    research["messages"], pending["llm_url"], pending["model"]
                ):
                    raw_chunks.append(chunk)
                    # Show accumulated text (raw, including any thinking tags)
                    answer_placeholder.markdown("".join(raw_chunks) + "▌")

                raw_answer = "".join(raw_chunks)
                full_answer, thinking = strip_thinking_tags(raw_answer)
                full_answer = _strip_tool_call_xml(full_answer)
                if not full_answer:
                    full_answer = "Search limit reached. I'll provide my best answer with the information I have."

                # Re-render cleaned answer (replaces raw streamed content)
                answer_placeholder.markdown(full_answer)
            else:
                # Already have the answer from the tool loop
                full_answer = research["answer"]
                full_answer, thinking = strip_thinking_tags(full_answer)
                full_answer = _strip_tool_call_xml(full_answer)
                st.markdown(full_answer)
                thinking = ""  # thinking was already stripped in _run_tool_loop

            # Show thinking in collapsible expander if present
            if thinking:
                with st.expander("🧠 Model's Reasoning Process"):
                    st.markdown(thinking)

        # Save to history
        st.session_state.chat_history = pending["history"] + [
            {"role": "user", "content": pending["question"]},
            {"role": "assistant", "content": full_answer},
        ]
        # Store thinking for history re-rendering
        if thinking:
            assistant_idx = len(st.session_state.chat_history) - 1
            st.session_state.chat_thinking[assistant_idx] = thinking
        st.session_state.chat_pending = None
```

> [!NOTE]
> The streaming phase shows raw text (including any `<think>` tags) during generation, then re-renders the cleaned version when streaming completes. This gives instant time-to-first-token feedback while ensuring the final display is clean.

- [ ] **Step 2: Run the app manually**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run streamlit run app.py`

Verify:
- Research status shows tool calls in real-time (expanded while working)
- When the LLM answers directly (no tools), the answer appears immediately
- When tools were used and max iterations exhausted, the answer streams token-by-token
- The cursor character `▌` appears during streaming and disappears when done
- Thinking tags are stripped after streaming completes

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: integrate streaming + real-time research status into chat UI"
```

---

## Phase 5: Tests

### Task 12: Update and add tests

**Files:**
- Modify: `tests/test_chat.py`

Update existing tests for the refactored API and add tests for new functions.

- [ ] **Step 1: Add test for `strip_thinking_tags`**

Add to `tests/test_chat.py`:

```python
from chat import strip_thinking_tags


def test_strip_thinking_tags_extracts_think():
    """Verify strip_thinking_tags extracts and strips <think> blocks."""
    text = "<think>Let me reason about this.</think>Here is the answer."
    cleaned, thinking = strip_thinking_tags(text)
    assert cleaned == "Here is the answer."
    assert "Let me reason" in thinking


def test_strip_thinking_tags_extracts_thinking():
    """Verify strip_thinking_tags extracts and strips <thinking> blocks."""
    text = "<thinking>Step by step analysis.</thinking>\n\nThe result is 42."
    cleaned, thinking = strip_thinking_tags(text)
    assert "The result is 42" in cleaned
    assert "Step by step" in thinking
    assert "<thinking>" not in cleaned


def test_strip_thinking_tags_handles_trailing_think():
    """Verify strip_thinking_tags handles unclosed trailing <think> blocks."""
    text = "Partial answer. <think>Still thinking about this"
    cleaned, thinking = strip_thinking_tags(text)
    assert "Partial answer" in cleaned
    assert "<think>" not in cleaned
    assert "Still thinking" in thinking


def test_strip_thinking_tags_no_tags():
    """Verify strip_thinking_tags returns text unchanged when no tags present."""
    text = "Just a plain answer with no thinking."
    cleaned, thinking = strip_thinking_tags(text)
    assert cleaned == text
    assert thinking == ""
```

- [ ] **Step 2: Add test for `_strip_tool_call_xml`**

```python
from chat import _strip_tool_call_xml


def test_strip_tool_call_xml_strips_sentinels():
    """Verify _strip_tool_call_xml strips Unicode sentinel tool call markers."""
    text = "Some text \u2458{\"name\": \"web_search\"}\u2459 more text"
    result = _strip_tool_call_xml(text)
    assert "Some text" in result
    assert "more text" in result
    assert "\u2458" not in result
    assert "web_search" not in result


def test_strip_tool_call_xml_strips_trailing():
    """Verify _strip_tool_call_xml strips unclosed trailing sentinel."""
    text = "Answer text \u2458{\"name\": \"web_search\""
    result = _strip_tool_call_xml(text)
    assert "Answer text" in result
    assert "\u2458" not in result


def test_strip_tool_call_xml_no_sentinels():
    """Verify _strip_tool_call_xml returns text unchanged when no sentinels."""
    text = "Just a normal answer."
    result = _strip_tool_call_xml(text)
    assert result == text
```

- [ ] **Step 3: Add test for `_run_tool_loop` returning text answer**

```python
def test_run_tool_loop_returns_text_answer():
    """Verify _run_tool_loop returns answer when LLM gives text response."""
    from chat import _run_tool_loop

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "AAPL looks strong."
    mock_response.choices[0].message.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("chat.OpenAI", return_value=mock_client):
        result = _run_tool_loop(
            question="How is AAPL?",
            ticker="AAPL",
            history=[],
            llm_url="http://localhost:8080/v1",
            model="qwen",
        )

    assert result["needs_final_call"] is False
    assert "AAPL looks strong" in result["answer"]
    assert result["tool_calls"] == []
```

- [ ] **Step 4: Add test for `_run_tool_loop` with max iterations**

```python
def test_run_tool_loop_needs_final_call_after_max_iterations():
    """Verify _run_tool_loop sets needs_final_call when loop exhausts."""
    from chat import _run_tool_loop, MAX_SEARCH_ITERATIONS

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_999"
    mock_tool_call.type = "function"
    mock_tool_call.function.name = "web_scrape"
    mock_tool_call.function.arguments = '{"url": "https://example.com"}'

    mock_response = MagicMock()
    mock_response.choices[0].message.content = None
    mock_response.choices[0].message.tool_calls = [mock_tool_call]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("chat.OpenAI", return_value=mock_client):
        with patch("chat._web_scrape", return_value="Scraped content"):
            result = _run_tool_loop(
                question="Read this article",
                ticker="AAPL",
                history=[],
                llm_url="http://localhost:8080/v1",
                model="qwen",
            )

    assert result["needs_final_call"] is True
    assert result["answer"] is None
    assert mock_client.chat.completions.create.call_count == MAX_SEARCH_ITERATIONS
```

- [ ] **Step 5: Add test for `stream_final_answer`**

```python
def test_stream_final_answer_yields_chunks():
    """Verify stream_final_answer yields text chunks from streaming response."""
    from chat import stream_final_answer

    # Mock a streaming response
    chunk1 = MagicMock()
    chunk1.choices[0].delta.content = "Hello "
    chunk2 = MagicMock()
    chunk2.choices[0].delta.content = "world!"
    chunk3 = MagicMock()
    chunk3.choices[0].delta.content = None  # Empty delta at end

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([chunk1, chunk2, chunk3])

    with patch("chat.OpenAI", return_value=mock_client):
        chunks = list(stream_final_answer(
            messages=[{"role": "user", "content": "test"}],
            llm_url="http://localhost:8080/v1",
            model="qwen",
        ))

    assert chunks == ["Hello ", "world!"]
```

- [ ] **Step 6: Add test for scrape content truncation**

```python
def test_web_scrape_truncates_long_content():
    """Verify _web_scrape truncates content exceeding MAX_SCRAPE_CONTENT_LENGTH."""
    from chat import _web_scrape, MAX_SCRAPE_CONTENT_LENGTH

    long_content = "A" * (MAX_SCRAPE_CONTENT_LENGTH + 1000)

    with patch("chat._MCPClient.get") as mock_mcp_get:
        mock_client = MagicMock()
        mock_client.call_tool.return_value = long_content
        mock_mcp_get.return_value = mock_client

        result = _web_scrape("https://example.com/long-article")

    assert len(result) < len(long_content)
    assert "[Content truncated" in result
```

- [ ] **Step 7: Run full test suite**

Run: `cd /home/akshaysdnd/Projects/bull_run && uv run pytest tests/ -v`
Expected: All tests pass (existing + new).

- [ ] **Step 8: Fix any failures**

If any existing tests break due to API changes, fix them. Common issues:
- `_execute_tool_call` no longer takes `search_count` parameter — update any test that calls it directly
- `ask_followup` now delegates to `_run_tool_loop` — mock behavior should be the same since the wrapper preserves the return shape

- [ ] **Step 9: Final commit**

```bash
git add -A
git commit -m "test: add tests for strip_thinking_tags, _strip_tool_call_xml, _run_tool_loop, stream_final_answer, scrape truncation"
```

---

## Self-Review Checklist

**Evaluation coverage:**

| Evaluation Finding | Task |
|---|---|
| #1 Parallelize tool calls | Task 5 |
| #2 Truncate scraped content | Task 2 |
| #3 Warm MCP server | Task 7 |
| #4 Real streaming | Tasks 8, 11 |
| #5 Fix chat history rendering | Task 9 |
| #6 Fix tool call display | Task 10 |
| #7 Centralize thinking-tag stripping | Task 1 |
| #8 Remove function-attribute state | Task 3 |
| #9 MCP reconnection | Task 6 |
| #10 Simplify search limiting | Task 4 |
| #11 Hybrid streaming | Tasks 8, 11 |

**Dependency order:** Tasks 1–4 are independent internal refactors. Task 5 refactors tool execution (depends on Task 4's simplified loop). Tasks 6–7 are independent MCP changes. Task 8 restructures `chat.py`'s public API (uses results from Tasks 1–5). Tasks 9–11 update `app.py` (depend on Task 8's new API). Task 12 validates everything.

**Test plan:** 8 new unit tests covering `strip_thinking_tags`, `_strip_tool_call_xml`, `_run_tool_loop`, `stream_final_answer`, and scrape truncation. Plus manual Streamlit verification for UI changes.

**No new dependencies:** Uses only `concurrent.futures` (stdlib) and existing `openai` streaming support.
