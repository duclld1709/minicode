"""Guards: everything that can stop or block the agent.

Two independent concerns live here:

- `Guards`: *when to stop* (step limit, token/cost budget, wall time). An agent
  without these can loop forever and burn money.
- `PermissionPolicy`: *what may run*. The model proposes tool calls; this policy
  decides, per call, whether to run it, ask the user, or refuse. It is the real
  defense against prompt injection: whatever a malicious file convinces the
  model to *propose*, a dangerous call still has to get past this check.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from minicode.llm.types import ToolCall, Usage
from minicode.tools.base import Tool

# --- Stopping conditions -----------------------------------------------------------


@dataclass
class Guards:
    """Limits for one `Agent.run()`. `None` means "no limit"."""

    max_steps: int = 30
    max_total_tokens: int | None = None
    max_cost_usd: float | None = None
    max_wall_seconds: float | None = 600.0

    def check(self, *, steps: int, usage: Usage, cost: float | None, elapsed: float) -> str | None:
        """Return a stop reason if any limit is reached, else None.

        Called *before* each LLM call, so a limit stops the next spend, not the last one.
        """
        if steps >= self.max_steps:
            return "max_steps"
        if self.max_total_tokens is not None and usage.total_tokens >= self.max_total_tokens:
            return "token_budget"
        if self.max_cost_usd is not None and cost is not None and cost >= self.max_cost_usd:
            return "cost_budget"
        if self.max_wall_seconds is not None and elapsed >= self.max_wall_seconds:
            return "wall_time"
        return None


# --- Command denylist (a second layer; permissions are the first) ------------------

DANGEROUS_COMMANDS: list[tuple[str, str]] = [
    # rm with flags aimed at /, /*, ~, $HOME or *: `rm -rf /`, `rm -r -f ~`; not `rm -rf build/`
    (r"\brm\s+(-\S+\s+)+(/|/\*|~/?|\$HOME|\*)(\s|;|$)", "deleting root, home or everything"),
    (r"\bsudo\b", "privilege escalation"),
    (r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b", "piping a download into a shell"),
    (r"\bmkfs(\.\w+)?\b", "formatting a filesystem"),
    (r"\bdd\b.*\bof=/dev/", "writing raw to a device"),
    (r">\s*/dev/(sd|nvme|hd)", "overwriting a disk device"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\bchmod\s+(-R\s+)?777\s+/(\s|$)", "making the whole filesystem world-writable"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "shutting down the machine"),
]


def dangerous_command_reason(command: str) -> str | None:
    """Return why `command` is blocked, or None if no pattern matches.

    A denylist can never be complete (there are endless ways to write `rm -rf /`),
    so it only catches obvious disasters, in every mode, even `auto`.
    """
    for pattern, reason in DANGEROUS_COMMANDS:
        if re.search(pattern, command):
            return reason
    return None


# --- Permission policy ---------------------------------------------------------------

PermissionMode = Literal["ask", "accept-edits", "auto"]
PromptAnswer = Literal["yes", "no", "always"]
PermissionPrompt = Callable[[ToolCall, Tool], PromptAnswer]


def deny_all(call: ToolCall, tool: Tool) -> PromptAnswer:
    """Default prompt for non-interactive use: say no to anything that needs asking."""
    return "no"


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


@dataclass
class PermissionPolicy:
    """Decides whether a proposed tool call may run.

    - `ask` (default): ask before every `write` and `exec` tool.
    - `accept-edits`: allow `write` tools, still ask for `exec`.
    - `auto`: never ask. The denylist still applies.
    Answering "always" allows that tool for the rest of the session.
    """

    mode: PermissionMode = "ask"
    prompt: PermissionPrompt = deny_all
    always_allowed: set[str] = field(default_factory=set)

    def decide(self, call: ToolCall, tool: Tool | None) -> Decision:
        if tool is None:
            return Decision(True)  # the registry will answer "unknown tool"
        if tool.name == "run_bash":
            reason = dangerous_command_reason(str(call.arguments.get("command", "")))
            if reason is not None:
                return Decision(False, f"Blocked by safety denylist ({reason}).")
        if not self._needs_prompt(tool):
            return Decision(True)
        answer = self.prompt(call, tool)
        if answer == "always":
            self.always_allowed.add(tool.name)
        if answer == "no":
            return Decision(False, "The user denied this action.")
        return Decision(True)

    def _needs_prompt(self, tool: Tool) -> bool:
        if tool.risk == "read" or self.mode == "auto" or tool.name in self.always_allowed:
            return False
        return not (self.mode == "accept-edits" and tool.risk == "write")
