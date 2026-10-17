"""Project memory: the workspace's AGENTS.md, injected into the system prompt.

AGENTS.md is where a team writes what every agent session should know about the
repo (how to run tests, conventions, gotchas). Loading it into *every* request
is what makes it "memory": the model is stateless, so anything it should always
know has to be in the context every time.
"""

from __future__ import annotations

from pathlib import Path

MEMORY_FILE = "AGENTS.md"
MAX_MEMORY_CHARS = 20_000


def load_project_memory(workspace: Path, max_chars: int = MAX_MEMORY_CHARS) -> str | None:
    """Return AGENTS.md from the workspace root, or None if there is none.

    Capped because it is paid for on every single LLM call.
    """
    path = workspace / MEMORY_FILE
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return None
    if len(text) > max_chars:
        text = (
            text[:max_chars] + f"\n\n[AGENTS.md truncated: {len(text) - max_chars} chars omitted]"
        )
    return text
