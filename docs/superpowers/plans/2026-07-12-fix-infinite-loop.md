# Fix Infinite Thinking Loops in Chat Model

This plan addresses the issue of the chat model (Qwen3) getting stuck in infinite thinking loops and repeating phrases during generation. This happens because the current generation calls lack limits on generation length and do not employ repetition penalties.

## Proposed Changes

### `bull_run` Application

#### [MODIFY] [chat.py](file:///home/akshaysdnd/Projects/bull_run/chat.py)

Update all instances where `client.chat.completions.create` is called to include the new sampling parameters and a `max_tokens` limit.

There are four locations where `client.chat.completions.create` is invoked:
1. `_run_tool_loop` (main call) - line ~532
2. `_run_tool_loop` (fallback call) - line ~541
3. `run_tool_loop_stream` (streaming loop) - line ~753
4. `stream_final_answer` (final answer generator) - line ~992

For the first 3 calls (`_run_tool_loop` and `run_tool_loop_stream`), update the parameters to include `max_tokens=4096` to prevent unbounded tool-calling iterations:

```python
client.chat.completions.create(
    model=model,
    messages=messages,
    tools=TOOLS, # If applicable
    temperature=1.0,
    top_p=0.95,
    presence_penalty=0.5,
    max_tokens=4096, # Prevent unbounded generation during tool loops
    extra_body={
        "top_k": 20,
        "min_p": 0.00
    },
    # stream=True # If applicable
)
```

For the 4th call (`stream_final_answer`), DO NOT set `max_tokens` so that the model can generate a full unrestricted answer. Use the same sampling parameters otherwise:

```python
client.chat.completions.create(
    model=model,
    messages=messages,
    temperature=1.0,
    top_p=0.95,
    presence_penalty=0.5,
    extra_body={
        "top_k": 20,
        "min_p": 0.00
    },
    stream=True
)
```

*Note: `top_k` and `min_p` are not standard OpenAI parameters, so they must be passed via `extra_body` to be forwarded to the `llama.cpp` server.*

## Verification Plan

### Manual Verification
1. Run the application and ask a complex question that triggers multiple tool calls.
2. Monitor the terminal running the `llama.cpp` server to ensure it does not get stuck in a decoding loop.
3. Verify that the UI streaming output updates smoothly and terminates correctly without repeating phrases.
4. Check the `llama.cpp` server logs to confirm that the `top_k`, `min_p`, and `presence_penalty` parameters are being received and applied.
