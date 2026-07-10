# Chat Progress and Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the chat feature to stream intermediate model thinking, display tool calls as they happen, and persist tool calls across chat turns.

**Architecture:** We will convert the synchronous `_run_tool_loop` into a generator `run_tool_loop_stream` that yields events (`content_chunk`, `tool_call_start`, `tool_call_result`, `done`). `app.py` will iterate over these events to update the UI progressively. Tool calls will be stored in `chat_history` alongside messages to persist them across chat turns.

**Tech Stack:** Python, Streamlit, OpenAI Python Client

## Global Constraints

- Preserve all existing imports and functionality not explicitly modified.
- Streamlit UI updates must avoid full page reruns where possible during streaming.
- Use `yield` to stream updates from `chat.py` to `app.py`.

---

### Task 1: Persist Tool Calls in Chat History

**Files:**
- Modify: `app.py`
- Modify: `chat.py`

**Interfaces:**
- Consumes: `st.session_state.chat_history` structure.
- Produces: Updated `st.session_state.chat_history` that includes `tool_calls`.

- [ ] **Step 1: Update chat history storage in `app.py`**
In `app.py` inside `on_chat_send`, the `st.session_state.chat_history` is updated. We need to save the tool calls and thinking associated with the assistant's message. Wait, `on_chat_send` just queues the `chat_pending`. The actual saving happens at the end of the `if st.session_state.chat_pending:` block.

Modify `app.py` where it saves to history (around line 565):
```python
        # Save to history
        st.session_state.chat_history = pending["history"] + [
            {"role": "user", "content": pending["question"]},
            {"role": "assistant", "content": full_answer, "tool_calls": st.session_state.chat_tool_calls, "thinking": thinking},
        ]
```
Note: We also move the `thinking` into the message dict rather than using a separate `chat_thinking` dict, making it cleaner.

- [ ] **Step 2: Update chat history rendering in `app.py`**
In `app.py` where it renders `st.session_state.chat_history` (around line 477):
```python
    # Render chat history using native chat containers
    for i, msg in enumerate(st.session_state.chat_history):
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        elif msg["role"] == "assistant":
            with st.chat_message("assistant"):
                st.markdown(msg["content"])
                
                # Render historical thinking
                thinking = msg.get("thinking", st.session_state.chat_thinking.get(i, ""))
                if thinking:
                    with st.expander("🧠 Model's Reasoning Process"):
                        st.markdown(thinking)
                        
                # Render historical tool calls
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    with st.expander("🔧 Tool Calls Made", expanded=False):
                        for j, tc in enumerate(tool_calls, 1):
                            tool = tc.get("tool", "unknown")
                            if tool == "searxng_search":
                                st.markdown(f"**{j}. 🔎 web_search** — `{tc.get('query', '')}`")
                            elif tool == "web_scrape":
                                url = tc.get("url", "")
                                display_url = url[:80] + "..." if len(url) > 80 else url
                                st.markdown(f"**{j}. 📄 web_scrape** — `{display_url}`")
                            else:
                                st.markdown(f"**{j}. {tool}**")
                            tc_result = tc.get("result", "")
                            if tc_result:
                                with st.expander(f"Result ({tool})"):
                                    st.text(tc_result[:2000])
```
Remove the isolated `elif st.session_state.chat_tool_calls:` block at the bottom of the chat section (around line 577), as tool calls will now be rendered within the history loop.

### Task 2: Implement Streaming Generator in `chat.py`

**Files:**
- Modify: `chat.py`

**Interfaces:**
- Consumes: `_run_tool_loop` logic.
- Produces: `run_tool_loop_stream` generator function.

- [x] **Step 1: Create `run_tool_loop_stream` generator**
Add this function to `chat.py` (you can replace `_run_tool_loop` or add it alongside). This handles `stream=True` and yields events.

```python
def run_tool_loop_stream(
    question: str, ticker: str, history: list[dict], llm_url: str, model: str, articles: Optional[list[dict]] = None, summary: Optional[str] = None
):
    tool_calls_list = []
    search_count = 0
    client = OpenAI(base_url=llm_url, api_key="not-needed", timeout=120.0)
    system_prompt = _build_system_prompt(ticker, articles, summary)

    messages = [{"role": "system", "content": system_prompt}]
    trimmed_history = history[-(MAX_CHAT_TURNS * 2):] if len(history) > MAX_CHAT_TURNS * 2 else history
    # Only keep role and content for API compatibility, drop tool_calls/thinking metadata from history
    clean_history = [{"role": m["role"], "content": m["content"]} for m in trimmed_history]
    messages.extend(clean_history)
    messages.append({"role": "user", "content": question})

    for iteration in range(MAX_SEARCH_ITERATIONS):
        try:
            stream = client.chat.completions.create(
                model=model, messages=messages, tools=TOOLS, temperature=0.1, stream=True
            )
        except Exception as e:
            logger.exception("LLM call failed")
            yield {"type": "error", "error": str(e)}
            return

        current_content = ""
        current_tool_calls = []

        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                current_content += delta.content
                yield {"type": "content_chunk", "chunk": delta.content, "full_content": current_content}
            
            if delta.tool_calls:
                for tc_chunk in delta.tool_calls:
                    while len(current_tool_calls) <= tc_chunk.index:
                        current_tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    tc = current_tool_calls[tc_chunk.index]
                    if tc_chunk.id: tc["id"] += tc_chunk.id
                    if tc_chunk.function.name: tc["function"]["name"] += tc_chunk.function.name
                    if tc_chunk.function.arguments: tc["function"]["arguments"] += tc_chunk.function.arguments

        if current_tool_calls:
            assistant_msg = {
                "role": "assistant",
                "tool_calls": current_tool_calls
            }
            if current_content:
                assistant_msg["content"] = current_content
            messages.append(assistant_msg)

            turn_search_count = 0
            tool_results = {}
            search_calls = [tc for tc in current_tool_calls if tc["function"]["name"] == "searxng_search"]
            other_calls = [tc for tc in current_tool_calls if tc["function"]["name"] != "searxng_search"]

            for tc in search_calls:
                args = json.loads(tc["function"]["arguments"])
                turn_search_count += 1
                if turn_search_count > MAX_PARALLEL_SEARCHES:
                    tool_results[tc["id"]] = ("searxng_search", f"Parallel search limit reached.", args, True)
                elif search_count >= MAX_SEARCHES:
                    tool_results[tc["id"]] = ("searxng_search", f"Search limit reached. STOP searching.", args, True)
                else:
                    search_count += 1
                    yield {"type": "tool_start", "tool": "searxng_search", "args": args}
                    result = _web_search(args.get("query", "").strip())
                    yield {"type": "tool_result", "tool": "searxng_search", "result": result}
                    tool_results[tc["id"]] = ("searxng_search", result, args, False)

            if other_calls:
                for tc in other_calls:
                    args = json.loads(tc["function"]["arguments"])
                    yield {"type": "tool_start", "tool": tc["function"]["name"], "args": args}
                
                # Execute in parallel
                with ThreadPoolExecutor(max_workers=3) as executor:
                    from types import SimpleNamespace
                    future_to_tc = {
                        executor.submit(_execute_tool_call, SimpleNamespace(
                            function=SimpleNamespace(name=tc["function"]["name"], arguments=tc["function"]["arguments"])
                        )): tc
                        for tc in other_calls
                    }
                    for future in as_completed(future_to_tc):
                        tc = future_to_tc[future]
                        args = json.loads(tc["function"]["arguments"])
                        try:
                            tool_name, result = future.result()
                        except Exception as e:
                            tool_name = tc["function"]["name"]
                            result = f"Tool execution failed: {e}"
                        yield {"type": "tool_result", "tool": tool_name, "result": result}
                        tool_results[tc["id"]] = (tool_name, result, args, False)

            for tc in current_tool_calls:
                tool_name, result, args, blocked = tool_results[tc["id"]]
                if not blocked:
                    display = {"tool": tool_name, "result": result}
                    if tool_name == "searxng_search": display["query"] = args.get("query", "")
                    elif tool_name == "web_scrape": display["url"] = args.get("url", "")
                    tool_calls_list.append(display)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            continue

        # Text response — done
        cleaned, thinking = strip_thinking_tags(current_content)
        cleaned = _strip_tool_call_xml(cleaned)
        yield {
            "type": "done",
            "messages": messages,
            "tool_calls": tool_calls_list,
            "trimmed_history": trimmed_history,
            "answer": cleaned,
            "thinking": thinking,
            "needs_final_call": False
        }
        return

    messages.append({
        "role": "system",
        "content": "Please provide your final answer now based on the research results above. Do not make any more tool calls."
    })
    yield {
        "type": "done",
        "messages": messages,
        "tool_calls": tool_calls_list,
        "trimmed_history": trimmed_history,
        "answer": None,
        "thinking": None,
        "needs_final_call": True
    }
```

### Task 3: Update UI to Process the Stream

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: Events from `run_tool_loop_stream`.
- Produces: Progressive UI updates.

- [ ] **Step 1: Replace Phase 1 and 2 in `app.py`**
In `app.py` around line 501, replace the `with st.status(...)` block and the Phase 2 block with logic that consumes the generator.

```python
        from chat import run_tool_loop_stream, stream_final_answer, strip_thinking_tags, _strip_tool_call_xml

        # Containers for streaming output
        status_container = st.container()
        assistant_container = st.chat_message("assistant")
        
        with status_container:
            status = st.status("🔍 Researching...", expanded=True)
            
        with assistant_container:
            thinking_expander = st.expander("🧠 Model's Reasoning Process")
            thinking_placeholder = thinking_expander.empty()
            answer_placeholder = st.empty()

        research = None
        tool_counter = 1
        
        # Phase 1: Research (Streaming)
        for event in run_tool_loop_stream(
            question=pending["question"], ticker=pending["ticker"], history=pending["history"],
            llm_url=pending["llm_url"], model=pending["model"], articles=pending["articles"], summary=pending["summary"]
        ):
            if event["type"] == "content_chunk":
                raw_text = event["full_content"]
                # Live extract and update thinking / answer
                cleaned, thinking = strip_thinking_tags(raw_text)
                if thinking:
                    thinking_placeholder.markdown(thinking + "▌")
                if cleaned:
                    answer_placeholder.markdown(cleaned + "▌")
            elif event["type"] == "tool_start":
                tool = event["tool"]
                args = event["args"]
                if tool == "searxng_search":
                    status.markdown(f"{tool_counter}. 🔎 web_search — `{args.get('query', '')}`")
                elif tool == "web_scrape":
                    url = args.get("url", "")
                    status.markdown(f"{tool_counter}. 📄 web_scrape — `{url[:80]}...`")
                tool_counter += 1
            elif event["type"] == "done":
                research = event
            elif event["type"] == "error":
                status.update(label="❌ Error", state="error")
                answer_placeholder.markdown(f"Error: {event['error']}")
                st.session_state.chat_pending = None
                st.rerun()

        st.session_state.chat_tool_calls = research["tool_calls"]
        
        # Final answer logic
        if research["needs_final_call"]:
            status.update(label="✍️ Writing answer...", state="running")
            raw_chunks = []
            for chunk in stream_final_answer(research["messages"], pending["llm_url"], pending["model"]):
                raw_chunks.append(chunk)
                raw_text = "".join(raw_chunks)
                cleaned, thinking = strip_thinking_tags(raw_text)
                if thinking:
                    thinking_placeholder.markdown(thinking + "▌")
                answer_placeholder.markdown(cleaned + "▌")
            
            raw_answer = "".join(raw_chunks)
            full_answer, thinking = strip_thinking_tags(raw_answer)
            full_answer = _strip_tool_call_xml(full_answer)
            if not full_answer:
                full_answer = "Search limit reached. I'll provide my best answer with the information I have."
        else:
            full_answer = research["answer"]
            thinking = research.get("thinking", "")
            
        status.update(label="✅ Research complete", state="complete")
        
        if thinking:
            thinking_placeholder.markdown(thinking)
        else:
            # Hide the expander if empty (Streamlit doesn't support hiding directly, but empty text is fine, or we could conditionally render it outside, but during stream it needs to exist. Leaving it empty is okay).
            pass
        answer_placeholder.markdown(full_answer)

        # Save to history
        st.session_state.chat_history = pending["history"] + [
            {"role": "user", "content": pending["question"]},
            {"role": "assistant", "content": full_answer, "tool_calls": st.session_state.chat_tool_calls, "thinking": thinking},
        ]
        st.session_state.chat_pending = None
        st.rerun()
```
