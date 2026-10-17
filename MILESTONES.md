# Milestones

Each milestone is a git tag (`m0` … `m8`). `git checkout mN` gives a runnable, green snapshot.
Run one milestone's tests with `uv run pytest -m mN`.

| Milestone | Status | Marker | Contract tests (copy into your repo) | What you write yourself |
|---|---|---|---|---|
| **M0** Setup & first LLM call | ✅ done | `m0` | `tests/contract/test_m0_types.py`, `tests/contract/test_m0_fake_client.py` | `llm/types.py` (`ToolCall`, `ToolResult`, `Usage.__add__`, `LLMResponse`, `Message` + constructors), `llm/base.py` (`LLMClient` Protocol), `llm/fake_client.py` (`FakeLLMClient`), `config.py` (`load_settings`), `llm/pricing.py` (`estimate_cost`), `llm/openai_client.py` (`to_input_items`, `from_response`), `chat.py` (`ChatSession.send`), `cli.py` (`chat`, `chat_loop`) |
| **M1** Providers, streaming, structured output | ✅ done | `m1` | `tests/contract/test_m1_adapters.py`, `tests/contract/test_m1_structured.py` | `llm/anthropic_client.py` (`to_messages`, `to_tool`, `from_message`, `AnthropicClient.complete` incl. streaming), streaming branch of `OpenAIClient.complete`, `llm/structured.py` (`complete_structured`, `extract_json`, `format_validation_error`), `llm/factory.py` (anthropic branch), streaming printer in `cli.py` |
| **M2** Tool calling | ✅ done | `m2` | `tests/contract/test_m2_registry.py`, `tests/contract/test_m2_fs_tools.py`, `tests/contract/test_m2_shell.py` | `tools/base.py` (`Tool`, `ToolRegistry.register/schemas/execute`, `ToolError`, `truncate_output`), `tools/fs.py` (`resolve_in_workspace`, `FileTools.read_file/list_dir/glob/grep/write_file/edit_file`), `tools/shell.py` (`find_bash`, `scrubbed_env`, `ShellTool.run_bash`), `tools/toolbelt.py` (`build_registry`) |
| **M3** Agent loop & guards | ✅ done | `m3` | `tests/contract/test_m3_agent.py`, `tests/contract/test_m3_permissions.py`, `tests/contract/test_m3_guards.py` | `agent/loop.py` (`Agent.run`, `_loop`, `_execute`, `_close_dangling_tool_calls`, `AgentResult`, `AgentListener`), `agent/guards.py` (`Guards.check`, `dangerous_command_reason`, `PermissionPolicy.decide`), `agent/prompts.py` (`build_system_prompt`), `ui.py` (`RichListener`, `make_permission_prompt`), `cli.py` (`run`, REPL `agent_repl`, `build_agent`) |
| **M4** MCP | ✅ done | `m4` | `tests/contract/test_m4_mcp.py` | `mcp/server.py` (`build_server_registry`, `create_mcp_server`, `serve_stdio`), `mcp/client.py` (`load_mcp_config`, `McpConnection` start/list_tools/call_tool/close, `tool_name`, `result_text`, `tools_from_connection`, `McpManager`), `Tool.input_schema` + `Tool.schema()`, `cli.py` (`mcp-serve`, `mcp_tools`) |
| M5 Harness / context engineering | ⏳ | `m5` | — | — |
| M6 Workflow patterns | ⏳ | `m6` | — | — |
| M7 Observability & evals | ⏳ | `m7` | — | — |
| M8 Polish | ⏳ | `m8` | — | — |

Learning notes: `docs/learning/mN-*.md`. SDK details: `docs/sdk-notes.md`.

## M0 — Setup & first LLM call

- `uv` project, Python 3.12, pinned `openai==3.33.0` / `anthropic==1.15.0`.
- Settings precedence: `.minicode/config.toml` < `.env` < environment.
- `minicode chat` is a multi-turn REPL that prints `in N | out M | $cost | session $total` after each turn.
- OpenAI adapter on the **Responses API** with `store=False` (stateless, full history resent).
  It already translates tool calls/results, so it is ready for M2.
- `FakeLLMClient` handles scripted offline tests and records every call.
- Acceptance: offline suite green (`uv run pytest`). Live smoke test: `uv run pytest --run-live -m live`.

## M1 — Provider abstraction, streaming, structured output

- `AnthropicClient` (Messages API). Tool results are sent inside a `user` message, and stop reasons
  are mapped to `end_turn` / `tool_use` / `max_tokens` / `other`.
- Both adapters stream when `on_text` is given (`responses.stream` / `messages.stream`). Otherwise they
  make a plain `create` call. Either way the final `LLMResponse` is built by the same `from_*` function.
- `complete_structured(llm, prompt, Model, max_retries=2)` puts the JSON Schema in the prompt, then
  validates with pydantic. When validation fails, it sends the error back to the model and asks it to
  fix the reply. It makes at most `1 + max_retries` calls, then raises `StructuredOutputError`.
- To switch provider, change `MINICODE_PROVIDER` (`openai` | `anthropic`). `minicode chat` now streams.
- Adapter contract: the constructor is `Client(model, *, api_key=None, sdk=None)`. Contract tests
  inject an SDK stub that returns objects in the real SDK format.
- Acceptance: the offline suite is green. Live tests (`--run-live`) passed against OpenAI. Anthropic is
  covered offline only, because there is no key in the dev environment.

## M2 — Tool calling

- `Tool(name, description, input_model, handler, risk)`. The handler receives **one argument**: the
  validated `input_model` instance.
- `ToolRegistry.execute()` never raises. Each of these becomes `ToolResult(is_error=True)` with a hint
  for the model: unknown tool (lists the available tools), arguments that were not valid JSON,
  arguments failing the schema (lists the bad fields and includes the schema), `ToolError` raised by a
  handler (message passed through), and any other exception (`crashed: Type: msg`).
- Output longer than `max_output_lines` / `max_output_chars` is cut in the middle (head and tail kept)
  with a `[truncated N lines]` marker.
- Filesystem tools:
  - `read_file` numbers lines and supports `offset` / `limit`;
  - `edit_file` does an exact, unique replace and keeps CRLF line endings;
  - `glob` and `grep` skip `.git`, virtualenvs and caches.
- `run_bash` runs `bash -c` in the workspace and returns the merged output plus `[exit code: N]`.
  A non-zero exit is **not** a tool error. It has a timeout, and the subprocess environment has
  `*API_KEY*`, `*TOKEN*`, `*SECRET*` and `*PASSWORD*` variables removed. On Windows it uses Git Bash,
  or `MINICODE_BASH` if set.
- Toolbelt contract: `build_registry(root, *, environ, bash=None) -> ToolRegistry`.
- Acceptance: an offline tool-use round trip with `FakeLLMClient`, a test for every error case, and a
  live round trip against OpenAI (`tests/e2e/test_m2_live.py`). Coverage of `tools/` is 93%.

## M3 — Agent loop & guards

- `Agent(llm, registry, guards, *, permission, system, listener, max_tokens, prices, clock)`. Its
  `run(task) -> AgentResult(final_text, steps, usage, stop_reason, cost)`.
- `history` is kept across `run()` calls, so a REPL session is one continuous conversation.
- Stop reasons:
  - `completed`;
  - `output_truncated`: the model hit `max_tokens` without calling a tool;
  - `max_steps`, `token_budget`, `cost_budget`, `wall_time`: checked *before* each LLM call;
  - `interrupted`: Ctrl+C.
- On Ctrl+C, every unanswered tool call gets an "Interrupted" error result. Without that, the next
  request would be rejected by both providers. The same clean-up runs before any other exception is
  re-raised.
- `PermissionPolicy(mode, prompt)`:
  - `ask` asks before `write` and `exec`;
  - `accept-edits` allows `write` and asks before `exec`;
  - `auto` never asks;
  - answering "always" allows that tool for the rest of the session;
  - the default `deny_all` prompt means a bare `Agent` refuses risky tools.
- The `run_bash` denylist (`rm -rf /`, `sudo`, `curl … | sh`, `mkfs`, `dd of=/dev/…`, fork bomb, …)
  is checked before permissions, in every mode, and the user is never asked about these.
- CLI:
  - `minicode run "task" [--cwd] [--mode] [--max-steps] [--max-cost]` exits with 0 only when the
    task completed;
  - `minicode [--cwd] [--mode]` with no subcommand starts the REPL;
  - `rich` shows `> tool(args)` and a 4-line preview of each result.
- Acceptance: `examples/buggy_calculator` (3 bugs) was fixed end to end with `gpt-6.1-sol` in 8 steps
  ($0.04, 2026-10-17): explore → pytest → 3× `edit_file` → pytest (9 passed) → summary.
  Every stopping condition and guard has an offline test.

## M4 — MCP

- `minicode mcp-serve [--cwd] [--allow-write]` serves the filesystem tools over stdio. It is read-only
  by default and never exposes `run_bash`. It wraps the same `ToolRegistry`, so schemas, the sandbox
  and error messages are identical to what the agent sees. Inspector:
  `npx @modelcontextprotocol/inspector uv run minicode mcp-serve --cwd .`
- `.minicode/mcp.json` (`{"mcpServers": {name: {command, args, env, cwd}}}`) is loaded by `run` and the
  REPL. Each tool becomes `mcp__<server>__<tool>` with risk `exec`. A server that fails to start is
  reported as a warning and skipped.
- Sync/async bridge: each `McpConnection` runs `asyncio.run(...)` in a daemon thread and holds the
  `Client` session open. Handlers submit coroutines with `run_coroutine_threadsafe(...).result(timeout)`.
- `python -m minicode` works (`__main__.py`). Tests use it to start our server as a subprocess.
- Acceptance: the integration tests run `python -m minicode mcp-serve` as a real subprocess and call
  its tools through the client: list, call, errors, sandbox, `--allow-write`, agent + permission prompt,
  and a broken server. One more test covers the CLI path through `.minicode/mcp.json`.
- Startup fix: provider SDKs are imported lazily in `llm/factory.py`. CLI startup went from 11s to 2s
  on Windows.

## Interface changes (vs PROJECT_SPEC §3.2)

All are **additions**. Nothing in the spec signature was removed or renamed.

| Where | Change | Why |
|---|---|---|
| `LLMClient` | added attribute `model: str` | callers need it to estimate cost and label traces |
| `LLMClient.complete` | added keyword `on_text: Callable[[str], None] \| None = None` | streaming arrives in M1. Adding it now keeps the Protocol stable instead of changing it mid-course |
| `Message` | concrete design: `role`, `content: str`, `tool_calls: list[ToolCall]`, `tool_results: list[ToolResult]`, plus `Message.user/assistant/tool` | spec left the content type open; a flat message is easier to read than content blocks (see `docs/learning/m0-*.md`) |
| `LLMResponse.tool_calls`, `Usage` fields | have defaults (`[]`, `0`) | convenience when building values in tests; same fields |
| tool schema passed to `complete(tools=...)` | neutral shape `{"name", "description", "input_schema"}` | adapters convert to each provider's format |
| `Tool.handler` (M2) | called as `handler(validated_args)` with an `input_model` instance | the spec only said `Callable[..., str]`. One typed argument keeps handlers simple and fully typed |
| `ToolRegistry` (M2) | added `get(name)`, `names` and optional `max_output_lines` / `max_output_chars` | the agent loop needs a tool's `risk` for permission checks (M3) |
| `INVALID_JSON_KEY` (M2) | moved from `llm/openai_client.py` to `llm/types.py` | the tool layer must not import from a specific adapter |
| `Agent.__init__` (M3) | keyword-only `permission`, `system`, `listener`, `max_tokens`, `prices`, `clock` after the spec's `(llm, registry, guards)` | dependency injection: tests pass a fake clock, a scripted permission prompt and a null listener |
| `AgentResult` (M3) | added `cost: float \| None` | budget and summary display |
| `Tool` (M4) | added optional `input_schema: dict \| None = None` and `schema()` | MCP tools arrive as JSON Schema, not pydantic models. They use a permissive `input_model` (`AnyArguments`) and let the server validate |

## Deviations from the spec

- **Platform:** developed on Windows native (best-effort); Linux/WSL remains the primary target.
- **Live tests** need an explicit `--run-live` flag *and* a key (a key alone is not enough), so a plain
  `uv run pytest` never spends money.
- **Extra modules** outside the spec layout: `llm/factory.py` (provider → client), `chat.py`
  (`ChatSession`), `llm/structured.py`, `tools/toolbelt.py` and `ui.py` (terminal rendering, split
  out of `cli.py` to keep it thin).
- **Workspace sandbox** lives in `tools/fs.py` (`resolve_in_workspace`) since M2, not in `agent/guards.py`.
  It is enforced where paths are used, so no tool can skip it. `guards.py` (M3) owns permissions,
  budgets and the `run_bash` denylist.
- The symlink-escape test is skipped on Windows without symlink privileges. It runs on Linux/CI.
- **Extra dev deps** (approved): `pytest-cov`, `types-PyYAML` (added in M7 together with `pyyaml`).
