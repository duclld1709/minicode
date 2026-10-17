"""Terminal rendering for the agent: progress events, permission prompts, summaries.

Everything that comes from the model or from tools is printed as plain `Text`,
never as rich markup: a file containing "[red]..." (or something sneakier) must
not be able to restyle or fake the UI.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.text import Text

from minicode.agent.guards import PermissionPrompt, PromptAnswer
from minicode.agent.loop import AgentResult
from minicode.llm.types import ToolCall, ToolResult
from minicode.tools.base import Tool

ANSWERS: dict[str, PromptAnswer] = {
    "y": "yes",
    "yes": "yes",
    "n": "no",
    "no": "no",
    "a": "always",
    "always": "always",
}


def short_args(arguments: dict[str, Any], limit: int = 120) -> str:
    """`path='a.py', limit=20`, cut to `limit` characters."""
    text = ", ".join(
        f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in arguments.items()
    )
    return text if len(text) <= limit else text[: limit - 3] + "..."


def preview(text: str, max_lines: int = 4, max_chars: int = 300) -> str:
    """First few lines of a tool result, with a count of what was hidden."""
    lines = text.expandtabs(2).splitlines() or [""]  # read_file's tabs would waste width
    shown = "\n".join(lines[:max_lines])[:max_chars]
    hidden = len(lines) - max_lines
    return f"{shown}\n... ({hidden} more lines)" if hidden > 0 else shown


class RichListener:
    """Streams model text and shows each tool call with a short result preview."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self._mid_line = False
        self._last_call_id: str | None = None

    def on_text(self, chunk: str) -> None:
        self.console.print(Text(chunk), end="")
        self._mid_line = not chunk.endswith("\n")

    def on_tool_call(self, call: ToolCall) -> None:
        self.end_line()
        self.console.print(
            Text.assemble(
                ("> ", "bold cyan"), (call.name, "bold cyan"), f"({short_args(call.arguments)})"
            )
        )
        self._last_call_id = call.id

    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        if call.id != self._last_call_id:
            # Parallel calls print all calls first, then all results: say whose result this is.
            self.console.print(Text(f"  < {call.name}", style="cyan"))
        self._last_call_id = None
        style = "red" if result.is_error else "dim"
        indented = "\n".join(f"  {line}" for line in preview(result.content).splitlines())
        self.console.print(Text(indented, style=style))

    def on_notice(self, message: str) -> None:
        self.end_line()
        self.console.print(Text(f"[{message}]", style="magenta"))

    def end_line(self) -> None:
        if self._mid_line:
            self.console.print()
            self._mid_line = False


def make_permission_prompt(console: Console, read_answer: Callable[[], str]) -> PermissionPrompt:
    """Build the interactive y/n/a prompt used in `ask` and `accept-edits` modes."""

    def prompt(call: ToolCall, tool: Tool) -> PromptAnswer:
        detail = (
            call.arguments.get("command")
            if tool.name == "run_bash"
            else short_args(call.arguments, 300)
        )
        console.print(
            Text.assemble(
                ("Allow ", "bold yellow"), (tool.name, "bold"), f" ({tool.risk}): ", str(detail)
            )
        )
        while True:
            console.print(Text("[y]es / [n]o / [a]lways for this tool: ", style="yellow"), end="")
            try:
                reply = read_answer()
            except EOFError:
                return "no"  # no one to ask (stdin closed): refuse
            answer = ANSWERS.get(reply.strip().lower())
            if answer is not None:
                return answer

    return prompt


def format_summary(result: AgentResult) -> str:
    cost = "cost n/a" if result.cost is None else f"${result.cost:.4f}"
    return (
        f"{result.stop_reason} | {result.steps} steps | "
        f"in {result.usage.input_tokens} | out {result.usage.output_tokens} | {cost}"
    )
