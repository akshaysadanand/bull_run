# RAM Optimization — Implementation Plan

Efficient RAM usage for Bull Run + web-search-MCP without functional regression.

## Proposed Changes

### Component 1: MCP Server — Chrome Lifecycle

Currently, Chrome launches eagerly at server startup and renderer processes accumulate forever. This wastes ~2-3 GB when chat isn't being used.

#### [MODIFY] [server.py](file:///home/akshaysdnd/Projects/web-search-MCP/search_mcp/server.py)

**1a. Lazy browser launch** — Don't start Chrome until the first `web_scrape` call.

Move `pm.chromium.launch()` out of `run()` and into a lazy `_ensure_browser()` method called from `get_page()`. The `searxng_search` tool doesn't need a browser at all, so Chrome stays dormant during search-only usage.

**1b. Single shared context** — Reuse one browser context for all pages instead of creating a new context per `get_page()` call.

Currently each `get_page()` creates a new `browser.new_context()` → new Chrome renderer process (~300 MB-1 GB). Change to create one context at browser launch time and reuse it for all pages. Pages are lightweight; contexts are not.

**1c. Proper page cleanup** — Fix `release_page()` to actually close excess pages.

The current code uses `asyncio.get_event_loop().run_until_complete(page.close())` which silently fails inside an already-running async loop. Replace with scheduling the close via `asyncio.create_task()` or just `await page.close()` since all callers are async.

**1d. Idle timeout** — Kill the browser after 5 minutes of no `web_scrape` calls.

Add a `_last_activity` timestamp updated on every scrape. Run a background task that checks every 60 seconds and calls `browser.close()` if idle > 5 minutes. The next `web_scrape` call will re-launch via `_ensure_browser()`.

```python
class WebScrapeServer:
    def __init__(self):
        self.server = Server("web-search-mcp")
        self._playwright = None
        self.browser: Browser | None = None
        self._context = None
        self._page_pool: list[Page] = []
        self._max_pages = 2
        self._last_activity: float = 0
        self._idle_timeout = 300  # 5 minutes

    async def _ensure_browser(self) -> None:
        """Lazily launch browser + context on first use."""
        if self.browser is None or not self.browser.is_connected():
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            self.browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            self._context = await self.browser.new_context(
                user_agent="Mozilla/5.0 ...",
                viewport={"width": 1920, "height": 1080},
            )
            self._context.set_default_timeout(30000)
        self._last_activity = time.monotonic()

    async def get_page(self) -> Page:
        await self._ensure_browser()
        if self._page_pool:
            return self._page_pool.pop()
        return await self._context.new_page()

    async def release_page(self, page: Page) -> None:
        """Release page — close excess pages properly."""
        if len(self._page_pool) < self._max_pages:
            # Clear page state before pooling
            try:
                await page.goto("about:blank")
            except Exception:
                pass
            self._page_pool.append(page)
        else:
            try:
                await page.close()
            except Exception:
                pass

    async def _idle_watcher(self):
        """Background task: close browser after idle timeout."""
        while True:
            await asyncio.sleep(60)
            if (self.browser and self.browser.is_connected()
                    and self._last_activity
                    and time.monotonic() - self._last_activity > self._idle_timeout):
                await self._shutdown_browser()

    async def _shutdown_browser(self):
        """Close browser, context, and all pages."""
        self._page_pool.clear()
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None
```

> [!NOTE]
> `release_page` becomes `async` — the one call site in `scrape_url` already uses `finally:`, just change it to `await self.release_page(page)`.

---

### Component 2: Streaming Regex — State Machine

Currently, `strip_thinking_tags()` and `_strip_tool_call_xml()` run 12 regex operations on the full accumulated string for every token chunk. This is O(N²) CPU time. While it doesn't cause OOM, it wastes CPU and creates unnecessary allocations.

#### [MODIFY] [chat.py](file:///home/akshaysdnd/Projects/bull_run/chat.py)

**2a. Add `StreamingThinkingParser` class** — An incremental state machine that tracks whether we're inside `<think>` / `<thinking>` tags without re-scanning.

```python
class StreamingThinkingParser:
    """Incrementally separates thinking tags from content during streaming.
    
    Tracks state (inside/outside thinking tags) and accumulates
    thinking vs. visible content separately — no regex needed per chunk.
    """
    
    def __init__(self):
        self.thinking_parts: list[str] = []
        self.content_parts: list[str] = []
        self._in_thinking = False
        self._buffer = ""  # Small buffer for partial tag detection
    
    def feed(self, chunk: str) -> tuple[str, str]:
        """Feed a new chunk and return (visible_content, thinking_so_far).
        
        Handles partial tags across chunk boundaries using a small buffer.
        """
        self._buffer += chunk
        
        while self._buffer:
            if self._in_thinking:
                # Look for closing tag
                end_idx = self._find_close_tag(self._buffer)
                if end_idx is not None:
                    tag_name, tag_end = end_idx
                    self.thinking_parts.append(self._buffer[:tag_end - len(f"</{tag_name}>")])
                    self._buffer = self._buffer[tag_end:]
                    self._in_thinking = False
                elif self._might_have_partial_close(self._buffer):
                    break  # Wait for more data
                else:
                    self.thinking_parts.append(self._buffer)
                    self._buffer = ""
            else:
                # Look for opening tag
                open_idx = self._find_open_tag(self._buffer)
                if open_idx is not None:
                    tag_name, tag_start, tag_end = open_idx
                    self.content_parts.append(self._buffer[:tag_start])
                    self._buffer = self._buffer[tag_end:]
                    self._in_thinking = True
                elif self._might_have_partial_open(self._buffer):
                    # Flush everything except the potential partial tag
                    safe_end = self._safe_flush_point(self._buffer)
                    if safe_end > 0:
                        self.content_parts.append(self._buffer[:safe_end])
                        self._buffer = self._buffer[safe_end:]
                    break
                else:
                    self.content_parts.append(self._buffer)
                    self._buffer = ""
        
        return "".join(self.content_parts), "".join(self.thinking_parts)
    
    def finalize(self) -> tuple[str, str]:
        """Flush remaining buffer (treat unclosed thinking as thinking content)."""
        if self._buffer:
            if self._in_thinking:
                self.thinking_parts.append(self._buffer)
            else:
                self.content_parts.append(self._buffer)
            self._buffer = ""
        return "".join(self.content_parts), "".join(self.thinking_parts)
```

> [!NOTE]
> Implementation details for `_find_open_tag`, `_find_close_tag`, `_might_have_partial_*` are straightforward string searches (e.g., `str.find("<think>")`) — no regex needed.

**2b. Use the parser in `run_tool_loop_stream`** — Replace the per-chunk `strip_thinking_tags(current_content)` call on line 676 with `parser.feed(content_to_add)`.

**2c. Use the parser in `stream_final_answer` consumption** — The `stream_final_answer` generator itself stays unchanged (it just yields raw chunks). But add a `StreamingToolCallStripper` or defer `_strip_tool_call_xml` to finalize-only, since tool call XML only matters in the final output, not for live display.

---

### Component 3: App Streaming — Remove Redundant Regex

#### [MODIFY] [app.py](file:///home/akshaysdnd/Projects/bull_run/app.py)

**3a. Research phase (lines 548-559)** — `chat.py` already provides `current_thinking` in the event. Stop re-running `strip_thinking_tags` + `_strip_tool_call_xml` in `app.py`. Instead, have `chat.py` also provide `current_cleaned` in the event via the `StreamingThinkingParser`.

Before:
```python
if event["type"] == "content_chunk":
    raw_text = event["full_content"]
    current_thinking = event.get("current_thinking", "")
    cleaned, _ = strip_thinking_tags(raw_text)       # redundant
    cleaned = _strip_tool_call_xml(cleaned)           # redundant
```

After:
```python
if event["type"] == "content_chunk":
    cleaned = event["cleaned_content"]
    current_thinking = event.get("current_thinking", "")
```

**3b. Final answer phase (lines 596-606)** — Create a `StreamingThinkingParser` locally for the `stream_final_answer` loop instead of re-running regex on the full accumulated text each iteration.

Before:
```python
for chunk in stream_final_answer(...):
    raw_chunks.append(chunk)
    raw_text = "".join(raw_chunks)                    # O(N) join
    cleaned, thinking = strip_thinking_tags(raw_text) # O(N) regex × 8
    cleaned = _strip_tool_call_xml(cleaned)           # O(N) regex × 4
```

After:
```python
parser = StreamingThinkingParser()
for chunk in stream_final_answer(...):
    cleaned, thinking = parser.feed(chunk)            # O(len(chunk)) only
```

---

## What This Does NOT Change

- `strip_thinking_tags()` and `_strip_tool_call_xml()` **stay in the codebase** — they're still used for one-shot parsing (summarizer, final answer extraction, `_run_tool_loop` sync path). Only the per-token streaming calls are replaced.
- `warm_mcp()` stays — it still initializes the MCP stdio connection. It just won't launch Chrome anymore (that's deferred to first `web_scrape` call).
- `_MCPClient` singleton lifecycle is unchanged.
- All functional behavior (thinking extraction, tool call stripping, search/scrape) remains identical.

## Verification Plan

### Automated Tests
```bash
cd /home/akshaysdnd/Projects/bull_run && python -m pytest tests/ -v
```

### Manual Verification
1. **Baseline RAM**: Start Streamlit app, confirm no `chrome-headless-shell` processes running (`ps aux | grep chrome-headless`)
2. **Lazy launch**: Use chat with a `web_scrape` tool call, confirm Chrome starts only then
3. **Idle timeout**: Wait 5+ minutes without scraping, confirm Chrome processes are cleaned up
4. **Streaming correctness**: Send a question that triggers thinking + tool calls, verify:
   - Thinking appears in the expander during streaming
   - Final answer renders correctly
   - Tool calls display in history
5. **Memory profile**: Compare peak RSS during a multi-tool-call chat session before/after changes

## Expected RAM Savings

| Source | Before | After | Savings |
|---|---|---|---|
| Chrome (idle) | ~2-3 GB | 0 | **~2-3 GB** |
| Chrome (active, per-context) | ~1 GB × contexts | ~300 MB (single context) | **~700 MB** |
| Streaming string copies | ~2-3 MB peak | ~few KB | Negligible (CPU win) |
| **Total idle savings** | | | **~2-3 GB** |
