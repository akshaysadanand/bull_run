# Fix Empty Reasoning Process Dropdown

I have investigated the issue where the "Model's Reasoning Process" dropdown is empty, and I have found three distinct bugs causing the model's thinking to be lost or hidden.

## Findings

1. **State Reset on Tool Loop Iterations**: `run_tool_loop_stream` resets its `current_content` buffer after every tool call. Because `app.py` updates the Streamlit UI placeholder using only the *current* buffer (`event["full_content"]`), any thinking generated in previous iterations is instantly overwritten and cleared from the UI as soon as a new tool call starts.
2. **History Truncation**: When the chat completes, the thinking saved to `st.session_state.chat_history` only extracts the `<think>` tags from the *final* LLM response. All reasoning performed during the web search and scraping phases is completely discarded, resulting in an empty expander in the chat history.
3. **Trailing Regex Bug**: The `strip_thinking_tags` function has a bug where it successfully captures trailing (unclosed) `<think>` tags during streaming, but fails to capture trailing `<thinking>` tags. If a model uses `<thinking>`, the UI will stay blank until the closing `</thinking>` tag is finally emitted.

## Proposed Changes

### `chat.py`

#### [MODIFY] `chat.py`
- Update `strip_thinking_tags` to handle trailing `<thinking>` tags:
  ```python
  trailing += re.findall(r'<thinking>(?!.*</thinking>)(.*?)$', text, flags=re.DOTALL | re.IGNORECASE)
  ```
- Update `run_tool_loop_stream` to accumulate a `total_thinking` string across all iterations.
- Add `current_thinking` to the `content_chunk` event yield so `app.py` doesn't have to parse it.
- Include `total_thinking` in the `done` event payload so `app.py` can persist the full thinking history.

### `app.py`

#### [MODIFY] `app.py`
- Modify the streaming UI loop to accumulate `total_thinking` and display the combined reasoning (`total_thinking + current_thinking`) so that previous iterations remain visible.
- Update the final `chat_history` append logic to use the combined `total_thinking` rather than just the thinking from the final answer chunk.

## User Review Required

Please review the findings and proposed fix. If approved, I will implement these changes so the dropdown accurately displays and streams the model's full reasoning process.
