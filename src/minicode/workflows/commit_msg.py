"""Prompt chaining: `minicode commit-msg` = diff -> summary -> commit message.

Two small, focused calls instead of one big one:
1. summarize the diff into facts (what changed, where, why it seems to change);
2. turn those facts into a Conventional Commit message.

Each step has a narrow job and can be checked on its own. Step 2 never sees the
raw diff, only the summary, so it focuses on wording rather than on reading code.
No agent, no tools: a fixed sequence is enough for a fixed task.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from minicode.llm.base import LLMClient
from minicode.llm.types import Message, Usage

MAX_DIFF_CHARS = 30_000

SUMMARY_SYSTEM = "You read git diffs and report precisely what changed. No speculation."
SUMMARY_PROMPT = """\
Summarize this git diff as a short bullet list of concrete changes (files, functions, behaviour).
Mention anything that looks like a bug fix, a new feature, a refactor, docs or tests.

<diff>
{diff}
</diff>"""

MESSAGE_SYSTEM = "You write excellent git commit messages following Conventional Commits."
MESSAGE_PROMPT = """\
Write a commit message for the changes summarized below.
Format: `type(optional scope): subject` (imperative, lowercase, no period, max 72 chars), then a
blank line, then 1-4 short bullet points with the important details. Types: feat, fix, refactor,
docs, test, chore, perf. Output only the commit message.

<summary>
{summary}
</summary>"""


class NoChangesError(Exception):
    """There is nothing to describe (no staged or unstaged changes)."""


@dataclass
class CommitMessage:
    summary: str
    message: str
    usage: Usage


def read_diff(workspace: Path, timeout: float = 30.0) -> str:
    """Staged changes if any, else unstaged changes. Truncated to keep the prompt bounded."""
    for args in (["git", "diff", "--staged"], ["git", "diff"]):
        completed = subprocess.run(
            args, cwd=workspace, capture_output=True, timeout=timeout, check=False
        )
        if completed.returncode != 0:
            error = completed.stderr.decode("utf-8", errors="replace").strip()
            raise NoChangesError(f"git diff failed: {error}")
        diff = completed.stdout.decode("utf-8", errors="replace")
        if diff.strip():
            return diff[:MAX_DIFF_CHARS]
    raise NoChangesError("No changes to describe: the working tree is clean.")


def write_commit_message(llm: LLMClient, diff: str) -> CommitMessage:
    """The chain itself: two calls, the output of the first is the input of the second."""
    summary = llm.complete(
        [Message.user(SUMMARY_PROMPT.format(diff=diff))],
        system=SUMMARY_SYSTEM,
        tools=[],
        max_tokens=800,
    )
    message = llm.complete(
        [Message.user(MESSAGE_PROMPT.format(summary=summary.text))],
        system=MESSAGE_SYSTEM,
        tools=[],
        max_tokens=400,
    )
    return CommitMessage(
        summary=summary.text.strip(),
        message=message.text.strip(),
        usage=summary.usage + message.usage,
    )
