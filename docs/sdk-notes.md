# SDK notes (verified against installed source, 2026-10-17)

Versions pinned in `pyproject.toml`. These notes were checked by reading the installed
packages under `.venv/Lib/site-packages/`, not from memory. Re-verify when bumping a pin.

| Package     | Version | Python | Used from |
|-------------|---------|--------|-----------|
| `openai`    | 3.33.0  | ≥3.10  | M0        |
| `anthropic` | 1.15.0  | ≥3.10  | M1        |
| `mcp`       | 2.3.0   | ≥3.10  | M4 (not yet a dependency) |

## OpenAI — Responses API (`openai/resources/responses/responses.py`)

```python
client = openai.OpenAI(api_key=...)
resp = client.responses.create(
    model="...",
    instructions="system prompt",            # system prompt goes here, not in `input`
    input=[...],                             # list of input items (below)
    tools=[{"type": "function", "name": "read_file", "description": "...",
            "parameters": {...json schema...}, "strict": False}],
    max_output_tokens=4096,
    store=False,                             # we stay stateless and resend history
    stream=True,                             # optional (M1): yields events
)
```

Input items (`openai/types/responses/response_input_item_param.py`):

- message: `{"role": "user" | "assistant" | "developer", "content": "text"}`
- tool call the model made earlier: `{"type": "function_call", "call_id", "name", "arguments": "<json str>"}`
- our tool result: `{"type": "function_call_output", "call_id", "output": "text"}`, with **no** `is_error` flag
  (we prefix `ERROR:` ourselves).

Response (`openai/types/responses/response.py`):

- `resp.output`: list of items, where `type == "message"` (text in `content[].text`) or
  `type == "function_call"` (`call_id`, `name`, `arguments` as a JSON **string**).
- `resp.output_text`: a convenience property that joins all text.
- `resp.status`: `completed` | `incomplete` | ...; `resp.incomplete_details.reason`, e.g. `max_output_tokens`.
  There is no `stop_reason`; we derive one.
- `resp.usage.input_tokens` / `output_tokens` (plus `input_tokens_details.cached_tokens`,
  `output_tokens_details.reasoning_tokens`).
- Streaming text event: `type == "response.output_text.delta"` with `.delta`.
- `openai.omit` is the sentinel for "don't send this parameter".

Gotcha: with reasoning models and `store=False`, don't resend `function_call` items with the
server `id` (`fc_...`), only `call_id`. Otherwise the API expects the matching reasoning item too.

## Anthropic — Messages API (`anthropic/resources/messages/messages.py`)

```python
client = anthropic.Anthropic(api_key=...)
msg = client.messages.create(
    model="...",
    max_tokens=4096,  # max_tokens is required
    system="system prompt",
    messages=[{"role": "user", "content": "..."}],
    tools=[{"name": "read_file", "description": "...", "input_schema": {...}}],
)
# streaming (M1): with client.messages.stream(...) as s: for text in s.text_stream: ...
```

- `msg.content`: list of blocks, `type == "text"` (`.text`) or `type == "tool_use"` (`.id`, `.name`,
  `.input` as a **dict** that is already parsed).
- `msg.stop_reason`: `end_turn` | `max_tokens` | `stop_sequence` | `tool_use` | `pause_turn` | `refusal` |
  `model_context_window_exceeded`.
- `msg.usage.input_tokens` / `output_tokens`.
- Tool results go back **inside a `user` message**:
  `{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "...", "content": "...", "is_error": True}]}`.
  All results for one assistant turn belong in one user message.

## MCP Python SDK v2 (`mcp/server/mcpserver/server.py`, `mcp/client/client.py`)

v2 renamed the high-level APIs. `FastMCP` became `MCPServer`, and there is a new high-level `Client`.

Server:
```python
from mcp.server import MCPServer

server = MCPServer("minicode")


@server.tool()  # schema inferred from type hints + docstring
def read_file(path: str) -> str: ...


server.add_tool(fn, name=..., description=...)  # programmatic registration
server.run()  # transport="stdio" by default (sync call)
```

Client (async only):
```python
from mcp import Client
from mcp.client.stdio import StdioServerParameters

async with Client(StdioServerParameters(command="uv", args=["run", "minicode", "mcp-serve"])) as c:
    tools = await c.list_tools()  # ListToolsResult(.tools)
    result = await c.call_tool("read_file", {"path": "a.py"})
    # CallToolResult: .content (list of blocks), .structured_content, .is_error
```

`Client(...)` also accepts an `MCPServer` instance for in-process tests. Our `Tool.handler` is sync,
so M4 needs a small bridge (a background event loop thread) to call the async client.
