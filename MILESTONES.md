# Milestones

Each milestone is a git tag (`m0` … `m8`). `git checkout mN` gives a runnable, green snapshot.
Run one milestone's tests with `uv run pytest -m mN`.

| Milestone | Status | Marker | Contract tests (copy into your repo) | What you write yourself |
|---|---|---|---|---|
| **M0** Setup & first LLM call | ✅ done | `m0` | `tests/contract/test_m0_types.py`, `tests/contract/test_m0_fake_client.py` | `llm/types.py` (`ToolCall`, `ToolResult`, `Usage.__add__`, `LLMResponse`, `Message` + constructors), `llm/base.py` (`LLMClient` Protocol), `llm/fake_client.py` (`FakeLLMClient`), `config.py` (`load_settings`), `llm/pricing.py` (`estimate_cost`), `llm/openai_client.py` (`to_input_items`, `from_response`), `chat.py` (`ChatSession.send`), `cli.py` (`chat`, `chat_loop`) |
| M1 Providers, streaming, structured output | ⏳ | `m1` | — | — |
| M2 Tool calling | ⏳ | `m2` | — | — |
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

## Interface changes (vs PROJECT_SPEC §3.2)

All are **additions**. Nothing in the spec signature was removed or renamed.

| Where | Change | Why |
|---|---|---|
| `LLMClient` | added attribute `model: str` | callers need it to estimate cost and label traces |
| `LLMClient.complete` | added keyword `on_text: Callable[[str], None] \| None = None` | streaming arrives in M1. Adding it now keeps the Protocol stable instead of changing it mid-course |
| `Message` | concrete design: `role`, `content: str`, `tool_calls: list[ToolCall]`, `tool_results: list[ToolResult]`, plus `Message.user/assistant/tool` | spec left the content type open; a flat message is easier to read than content blocks (see `docs/learning/m0-*.md`) |
| `LLMResponse.tool_calls`, `Usage` fields | have defaults (`[]`, `0`) | convenience when building values in tests; same fields |
| tool schema passed to `complete(tools=...)` | neutral shape `{"name", "description", "input_schema"}` | adapters convert to each provider's format |

## Deviations from the spec

- **Platform:** developed on Windows native (best-effort); Linux/WSL remains the primary target.
- **Live tests** need an explicit `--run-live` flag *and* a key (a key alone is not enough), so a plain
  `uv run pytest` never spends money.
- **Extra modules** outside the spec layout: `llm/factory.py` (provider → client) and `chat.py` (`ChatSession`).
- **Extra dev deps** (approved): `pytest-cov`, `types-PyYAML` (added in M7 together with `pyyaml`).
