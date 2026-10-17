# Milestones

Each milestone is a git tag (`m0` … `m8`). `git checkout mN` gives a runnable, green snapshot.
Run one milestone's tests with `uv run pytest -m mN`.

| Milestone | Status | Marker | Contract tests (copy into your repo) | What you write yourself |
|---|---|---|---|---|
| **M0** Setup & first LLM call | ✅ done | `m0` | `tests/contract/test_m0_types.py`, `tests/contract/test_m0_fake_client.py` | `llm/types.py` (`ToolCall`, `ToolResult`, `Usage.__add__`, `LLMResponse`, `Message` + constructors), `llm/base.py` (`LLMClient` Protocol), `llm/fake_client.py` (`FakeLLMClient`), `config.py` (`load_settings`), `llm/pricing.py` (`estimate_cost`), `llm/openai_client.py` (`to_input_items`, `from_response`), `chat.py` (`ChatSession.send`), `cli.py` (`chat`, `chat_loop`) |
| **M1** Providers, streaming, structured output | ✅ done | `m1` | `tests/contract/test_m1_adapters.py`, `tests/contract/test_m1_structured.py` | `llm/anthropic_client.py` (`to_messages`, `to_tool`, `from_message`, `AnthropicClient.complete` incl. streaming), streaming branch of `OpenAIClient.complete`, `llm/structured.py` (`complete_structured`, `extract_json`, `format_validation_error`), `llm/factory.py` (anthropic branch), streaming printer in `cli.py` |
| **M2** Tool calling | ✅ done | `m2` | `tests/contract/test_m2_registry.py`, `tests/contract/test_m2_fs_tools.py`, `tests/contract/test_m2_shell.py` | `tools/base.py` (`Tool`, `ToolRegistry.register/schemas/execute`, `ToolError`, `truncate_output`), `tools/fs.py` (`resolve_in_workspace`, `FileTools.read_file/list_dir/glob/grep/write_file/edit_file`), `tools/shell.py` (`find_bash`, `scrubbed_env`, `ShellTool.run_bash`), `tools/toolbelt.py` (`build_registry`) |
| M3 Agent loop & guards | ⏳ | `m3` | — | — |
| M4 MCP | ⏳ | `m4` | — | — |
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

## Deviations from the spec

- **Platform:** developed on Windows native (best-effort); Linux/WSL remains the primary target.
- **Live tests** need an explicit `--run-live` flag *and* a key (a key alone is not enough), so a plain
  `uv run pytest` never spends money.
- **Extra modules** outside the spec layout: `llm/factory.py` (provider → client), `chat.py`
  (`ChatSession`), `llm/structured.py` and `tools/toolbelt.py`.
- **Workspace sandbox** lives in `tools/fs.py` (`resolve_in_workspace`) since M2, not in `agent/guards.py`.
  It is enforced where paths are used, so no tool can skip it. `guards.py` (M3) owns permissions,
  budgets and the `run_bash` denylist.
- The symlink-escape test is skipped on Windows without symlink privileges. It runs on Linux/CI.
- **Extra dev deps** (approved): `pytest-cov`, `types-PyYAML` (added in M7 together with `pyyaml`).
