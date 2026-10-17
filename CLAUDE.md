# CLAUDE.md — conventions for working on minicode

`minicode` is a **reference implementation** of a Claude Code–style coding agent, written
for someone learning AI engineering. They will run it, rewrite it milestone by milestone,
and diff their code against this repo. The full brief is in `PROJECT_SPEC.md`.

## Priorities
**Readable > correct > complete > optimized.** No clever code. Short functions (~≤50 lines),
full type hints, docstrings that explain *why*. No global/module-level mutable state.

## Milestone workflow (M0 → M8)
1. State a short plan at the start of each milestone.
2. At the end, all of these must pass:
   `uv run pytest` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy src`
3. Update `MILESTONES.md` and write `docs/learning/mN-<slug>.md` (Vietnamese, 6 sections per spec §6).
4. Commit (Conventional Commits), then `git tag mN`. Every tag must run and be green on its own.
5. **Stop and wait for the user's confirmation** unless they said "làm tiếp hết".

## Hard rules
- **No agent frameworks** (LangChain, LangGraph, LlamaIndex, CrewAI, AutoGen, Agent SDK). The loop is ours.
- Allowed deps — runtime: `anthropic`, `openai`, `mcp`, `pydantic` v2, `typer`, `rich`,
  `python-dotenv`, `httpx`, `pyyaml`; dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`,
  `mypy`, `types-PyYAML`. **Ask before adding anything else.** Add a dep only in the milestone that needs it.
- SDK versions are pinned exactly in `pyproject.toml`. Check SDK APIs against the installed source
  in `.venv/Lib/site-packages/...` or current docs, never from memory. Findings: `docs/sdk-notes.md`.
- Public API in spec §3.2 (`llm/types.py`, `LLMClient`, `Tool`, `ToolRegistry`, `Agent`) is a
  contract shared with the learner's contract tests. Do not change it casually; if you must,
  record why under "Interface changes" in `MILESTONES.md`.
- Dependency injection everywhere (LLM client, registry, permission prompt, environment).
  Offline tests use `FakeLLMClient` (`src/minicode/llm/fake_client.py`).
- Model IDs live in `.env` / `.minicode/config.toml`, not in code (pricing table is the only exception: it is data).

## Language
- English: code, identifiers, comments, docstrings, README, commit messages.
- Vietnamese: `docs/learning/*.md`.

## Tests
- `tests/contract/` — public API only; the learner copies these. Marker per milestone: `@pytest.mark.mN`.
- `tests/unit/` — internals. `tests/e2e/` — real API, marker `live`.
- Live tests run only with `uv run pytest --run-live` (they cost money). Default run is fully offline.
- Coverage target ≈80% for `agent/` and `tools/`: `uv run pytest --cov=minicode`.

## Safety
- Never print or log API keys. Settings store keys as `SecretStr`; traces must mask secrets.
- `.env` is git-ignored — check `git status` before every commit.
- All file paths a tool touches must resolve inside the workspace (`--cwd`).

## Platform
Primary target is Linux/WSL; Windows native is best-effort and is where this repo is developed.
`uv` lives in `%USERPROFILE%\.local\bin` (add to PATH if a shell can't find it). From M2,
`run_bash` needs a `bash` on PATH (Git Bash on Windows). Use `pathlib`, never hardcode `/`.

## Common commands
```bash
uv sync                                   # install
uv run minicode chat                      # M0: multi-turn chat
uv run minicode run "task" --cwd DIR      # M3: one-shot agent (--mode ask|accept-edits|auto)
uv run minicode --cwd DIR                 # M3: agent REPL
# Run the buggy_calculator demo on a COPY (or git checkout it afterwards).
uv run pytest -m m0                       # one milestone's tests
uv run pytest --run-live -m live          # real API smoke tests
```
