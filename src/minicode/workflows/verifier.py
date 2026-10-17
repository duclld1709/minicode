"""Evaluator-optimizer: `--verify "pytest -q"`.

The agent (optimizer) says it is done; a check (evaluator) decides whether it
really is. If the check fails, its output goes back to the agent as feedback and
the agent tries again, up to `max_rounds` times.

Here the evaluator is a command, not another LLM: an exit code is objective and
free. This directly addresses the classic failure mode "the agent says it fixed
the bug but never ran the tests".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from minicode.agent.loop import Agent, AgentResult
from minicode.llm.types import Usage
from minicode.tools.base import truncate_output

CheckRunner = Callable[[str], tuple[int, str]]
"""Runs a shell command and returns (exit code, output). Injected so tests need no shell."""

FEEDBACK = """\
I ran the verification command `{command}` and it failed (exit code {exit_code}). Output:

{output}

Find the cause and fix it, then reply when you are done. Do not change the verification \
command or weaken the tests to make it pass."""


@dataclass
class VerifiedRun:
    result: AgentResult  # the last agent run
    verified: bool
    rounds: int  # verification attempts made
    check_output: str = ""
    usage: Usage = field(default_factory=Usage)  # summed over all agent runs


def run_with_verification(
    agent: Agent,
    task: str,
    *,
    command: str,
    run_check: CheckRunner,
    max_rounds: int = 3,
    on_check: Callable[[int, str], None] | None = None,
) -> VerifiedRun:
    """Run the task, then verify; feed failures back until the check passes or rounds run out."""
    result = agent.run(task)
    usage = result.usage
    exit_code, output = -1, ""
    for round_number in range(1, max_rounds + 1):
        if result.stop_reason != "completed":
            # Stopped by a guard or Ctrl+C: re-prompting would override the user's limits.
            return VerifiedRun(result, False, round_number - 1, output, usage)
        exit_code, output = run_check(command)
        if on_check is not None:
            on_check(exit_code, output)
        if exit_code == 0:
            return VerifiedRun(result, True, round_number, output, usage)
        if round_number == max_rounds:
            break
        short_output = truncate_output(output, max_lines=80, max_chars=6_000)
        result = agent.run(
            FEEDBACK.format(command=command, exit_code=exit_code, output=short_output)
        )
        usage = usage + result.usage
    return VerifiedRun(result, False, max_rounds, output, usage)
