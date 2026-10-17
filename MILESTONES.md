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
| **M5** Harness / context engineering | ✅ done | `m5` | `tests/contract/test_m5_harness.py`, `tests/contract/test_m5_compaction.py`, `tests/contract/test_m5_prompt_injection.py` | `agent/prompts.py` (`PromptContext`, `build_system_prompt` + section functions, `read_git_status`, `wrap_tool_output`), `harness/memory.py` (`load_project_memory`), `harness/skills.py` (`parse_skill_file`, `discover_skills`, `make_skill_tool`), `agent/context.py` (`estimate_tokens`, `Compactor.maybe_compact`/`split_index`, `clear_old_tool_results`, `summary_message`, `render_transcript`), compaction + wrapping hooks in `Agent` |
| **M6** Workflow patterns | ✅ done | `m6` | `tests/contract/test_m6_chaining_routing.py`, `tests/contract/test_m6_parallel.py`, `tests/contract/test_m6_subagent_verifier.py`, `tests/contract/test_m6_todo.py` | `workflows/commit_msg.py` (`read_diff`, `write_commit_message`), `agent/router.py` (`TaskRoute`, `Router.route`), `llm/metered.py` (`MeteredLLM`), parallel reads in `Agent._execute_all`/`_execute_parallel`, `Agent.add_usage`, `ToolRegistry.subset`, `workflows/subagent.py` (`DelegateTool`), `workflows/verifier.py` (`run_with_verification`), `tools/todo.py` (`TodoList`), `ShellTool.run` |
| **M7** Observability & evals | ✅ done | `m7` | `tests/contract/test_m7_tracing.py`, `tests/contract/test_m7_evals.py` | `tracing.py` (`mask_secrets`, `Tracer`, `TracedLLM`, `TraceListener`, `FanoutListener`, `load_trace`, `latest_trace`), `ui.py` (`render_trace`, `trace_totals`), `cli.py` (`replay`, `open_tracer`, run events), `evals.py` (`load_tasks`, `run_pytest`, `original_tests_pass`, `load_check`, `run_task`, `run_suite`, `summarize`, `save_results`, `comparison_table`), `evals/run_evals.py`, plus one eval task of your own |
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

## M5 — Harness / context engineering

- System prompt sections, in this order: identity, how to work, safety, environment (cwd, OS, date,
  `git status --short --branch`), project memory (`AGENTS.md`, max 20k chars), skills. Each optional
  section is included only when it has content.
- Skills live in `.minicode/skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`).
  The prompt lists only names and descriptions. The `load_skill(name)` tool returns the body and lists
  the other files in the skill folder. The two sample skills (`write-pytest-tests`, `python-refactor`)
  and an `AGENTS.md` are in `examples/buggy_calculator/`.
- Every registry result is wrapped as `<tool_output tool="...">…</tool_output>` before it goes into
  history. A closing tag inside the content is neutralized. The safety section explains that wrapped
  content is data.
- Compaction (`Compactor`, small model) runs after each tool step once the estimated size (chars/4)
  reaches `compact_at_tokens` (default 100k, settable in `config.toml`):
  1. clear old tool results longer than 2,000 chars;
  2. if that is not enough, summarize everything before the last 6 steps. The user's requests are
     kept verbatim.

  The cut is always placed right before an assistant message. The summary call's usage counts toward
  the budget, and the listener shows a notice.
- Prompt injection test: a README with hidden instructions, and a scripted model that obeys them.
  The denylist blocks `curl | sh`, the sandbox blocks `../exfil.txt`, and in `ask` mode the user is
  asked about `cat ~/.ssh/id_rsa`. The test also documents the honest limitation of `auto` mode.
- Acceptance: compaction threshold, skills loaded only on demand, and injection tests, all offline.
  Live run with `gpt-6.1-sol` on 2026-10-17: the task "add tests for multiply" made the model call
  `load_skill("write-pytest-tests")` first and follow the skill (8 steps, $0.05).
- New dependencies: `pyyaml` (skill frontmatter), and `types-PyYAML` (dev).

## M6 — Workflow patterns

| Pattern | Where | How |
|---|---|---|
| Chaining | `minicode commit-msg` → `workflows/commit_msg.py` | Uses the staged diff, or the unstaged diff if nothing is staged. Call 1 (small model) summarizes it; call 2 writes a Conventional Commit message from the summary only |
| Routing | `agent/router.py`, `Agent(router=...)`, `--route/--no-route` (on by default) | The small model returns `TaskRoute(kind="question"\|"edit")` via `complete_structured`. `question` runs with `registry.subset(risk == "read")`. If routing fails, it falls back to `edit` |
| Parallelization | `Agent._execute_all` | Each run of consecutive `read` calls in one turn runs in a thread pool (max 8 workers). Results are collected in call order. Any other call is a barrier and runs alone |
| Orchestrator-workers | `delegate` tool → `workflows/subagent.py` | A fresh `Agent` with read-only filesystem tools and no `delegate`, max 15 steps. It returns its final report. Its usage is added to the parent through `Agent.add_usage` |
| Evaluator-optimizer | `minicode run … --verify "pytest -q" [--max-verify-rounds 3]` → `workflows/verifier.py` | After `completed`, the check command runs. A non-zero exit sends the output back to the agent as feedback. There are at most K checks, and no extra rounds if the agent stopped for another reason |

- `todo_write` replaces the whole plan (at most one item `in_progress`); `todo_read` shows it. Both have
  risk `read` and keep the plan in memory only.
- Bug found and fixed while building parallel reads: with `pool.map`, a Ctrl+C in one worker lost
  the results of reads that had already finished. A weak substring assertion in the M3 contract test
  ("ran" also appears in the "Interrupted … ran." placeholder) had hidden this. The test now also
  checks `is_error`. The fix collects futures one by one.
- Acceptance: at least one offline test per pattern (24 contract tests, plus CLI tests for `--verify`
  and `commit-msg`). Live runs with `gpt-6.1-sol` / `gpt-6-luna` on 2026-10-17:
  - "Fix the failing tests" `--verify "pytest -q"`: routed as `edit`; `todo_write` was used 4 times;
    5 parallel `read_file` calls; verified on the first check (12 steps, $0.09).
  - "Which functions raise…, use delegate": routed as `question`; 2 parallel `delegate` calls; no
    permission prompts in `ask` mode, because only read tools were available ($0.05).
  - `commit-msg` on the resulting diff produced `fix(calculator): correct arithmetic and median
    calculations` in 2 calls.

## M7 — Observability & evals

- **Tracing:** every `run` and REPL session writes `.minicode/traces/<stamp>-<id>.jsonl`. Event types
  are `session_start`, `run_start`, `llm_call` (label main/small, latency, tokens, cost, stop reason,
  text preview, tool calls), `tool_call` (arguments, latency, error flag, result size and preview),
  `notice`, `verify`, `run_end` and `error`. The events come from wrappers: `TracedLLM` wraps the
  client and `TraceListener` is fanned out next to the UI. The agent loop itself is unchanged.
- **Masking:** each line is masked before it is written. Known keys and key-like patterns
  (`sk-…`, `ghp_…`, `AKIA…`, `xox…-`) become `***`. A test makes the agent read a `.env` file
  containing a key and checks that the key never reaches disk. The committed results were also
  checked against the real key: no match.
- `minicode replay [trace] [--cwd]` pretty-prints a trace (the latest one by default) and ends with a
  totals line.
- **Evals:** 9 tasks in `evals/tasks/`.
  - Categories: bugfix ×2, feature, refactor (rename across files), question ×2, skill,
    injection ×2.
  - Each task has `task.yaml`, a `repo/` fixture and `check.py` with `check(ctx) -> (passed, reason)`.
    `ctx` holds the workspace, the original fixture, the final answer and the attempted tool calls.
  - Runs use `auto` mode, a fresh temp copy per task, the same `build_agent` as the CLI, and a $1
    budget per task.
  - Output: a results table plus `evals/results/<stamp>-<model>-<label>.json`, with one trace per
    task copied next to it. `--compare a.json b.json …` compares runs side by side.
- **Bug in our own check:** the first real run failed `injection_delete_tests`. The trace showed the
  model had *not* obeyed the injection: it fixed the bug and *added* tests. The byte-for-byte "tests
  unchanged" check was too strict. It was replaced by `original_tests_pass`: the original test
  functions must still exist, and the original tests must pass on the agent's code. Four tests cover
  the new check, the stale result was discarded, and the suite was re-run.
- **Results (2026-10-17), committed in `evals/results/`:**

  | config | pass | avg steps | tokens in/out | cost | time |
  |---|---|---|---|---|---|
  | `gpt-6.1-sol` (small: `gpt-6-luna`) | 9/9 | 6.0 | 109,785 / 3,618 | $0.256 | 160s |
  | `gpt-6-luna` as main | 9/9 | 7.7 | 165,071 / 5,733 | $0.019 | 145s |

  Both reached 100%, so the suite is saturated and harder tasks are needed to separate models.

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
| Tool results in `Agent.history` (M5) | content is now wrapped in `<tool_output tool="…">…</tool_output>` | marks untrusted data (spec §3.4). The three M3 contract assertions that compared content exactly now use `in`, so they pass with or without wrapping |
| `AgentListener` (M5) | added `on_notice(message)` | lets the UI report compaction. Custom listeners need the new method |
| `Agent.__init__` (M5) | added keyword `compactor: Compactor \| None = None` | compaction is optional and injected |
| `build_system_prompt` (M5) | now takes a `PromptContext` instead of `(workspace, *, today, os_name)` | the prompt has many optional inputs now; one dataclass keeps the call readable (not part of §3.2) |
| `Agent` (M6) | added keywords `router` and `max_parallel_tools`, and the method `add_usage(usage)` | routing and parallel reads; subagent usage counts toward the parent's budget |
| `ToolRegistry` (M6) | added `subset(keep) -> ToolRegistry` | a read-only view of the toolbelt for `question` tasks and subagents |
| Listener event order (M6) | for a run of parallel reads: all `on_tool_call` events first, then all `on_tool_result` events in call order | calls are announced before they start together. `RichListener` labels results that are not printed next to their call |

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
- **Extra dev deps** (approved): `pytest-cov`, and `types-PyYAML` (added in M5 together with `pyyaml`,
  which skills need for their frontmatter).
