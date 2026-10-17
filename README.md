# minicode

A mini coding agent (Claude Code–style) built from scratch in Python — no agent frameworks,
just an LLM client, a tool registry, and a hand-written agent loop.

> Work in progress, built milestone by milestone (see [MILESTONES.md](MILESTONES.md)).
> The full README (demo, architecture, eval results) comes in M8.

## Quick start (M0)

```bash
uv sync
cp .env.example .env      # then fill in your key and model IDs
uv run minicode chat      # multi-turn chat; prints tokens + estimated cost per turn
uv run pytest             # offline test suite
```
