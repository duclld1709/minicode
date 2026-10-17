# minicode

A mini coding agent (Claude Code–style) built from scratch in Python — no agent frameworks,
just an LLM client, a tool registry, and a hand-written agent loop.

> Work in progress, built milestone by milestone (see [MILESTONES.md](MILESTONES.md)).
> The full README (demo, architecture, eval results) comes in M8.

## Quick start

```bash
uv sync
cp .env.example .env      # then fill in your key and model IDs

# One-shot task (asks before edits and commands; --mode accept-edits|auto to relax)
uv run minicode run "Fix the failing tests" --cwd examples/buggy_calculator
git checkout -- examples/buggy_calculator   # reset the demo afterwards

uv run minicode --cwd ./my-project          # interactive agent (REPL)
uv run minicode chat                        # plain multi-turn chat, no tools
uv run minicode mcp-serve --cwd .           # expose read-only file tools over MCP (stdio)
uv run pytest                               # offline test suite
```
