"""Tool definitions and the registry that executes them.

Key idea: the model only *proposes* a tool call (a name plus JSON arguments). Our
code decides what actually runs. `ToolRegistry.execute` is that decision point,
and it never raises: every failure becomes a `ToolResult(is_error=True)` whose
message tells the model how to fix its next attempt. An agent that crashes on a
typo in a tool name is useless; one that reads "Unknown tool 'read'. Available
tools: read_file, ..." usually corrects itself on the next turn.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from minicode.llm.structured import format_validation_error
from minicode.llm.types import INVALID_JSON_KEY, ToolCall, ToolResult

Risk = Literal["read", "write", "exec"]

# Both providers accept tool names matching this pattern.
TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ToolError(Exception):
    """Raised by a handler for an *expected* failure (file not found, bad regex...).

    The message is shown to the model as-is, so write it as advice: what went
    wrong and what to do instead.
    """


@dataclass
class Tool:
    """A capability exposed to the model.

    `handler` is called with one argument: an instance of `input_model`, already
    validated. So handlers never see malformed input.
    """

    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[..., str]
    risk: Risk


@dataclass
class ToolRegistry:
    """Holds tools, publishes their schemas, and executes calls safely."""

    # Above read_file's max `limit` (500), so a normal page of a file is never cut.
    max_output_lines: int = 600
    max_output_chars: int = 40_000
    _tools: dict[str, Tool] = field(default_factory=dict, init=False, repr=False)

    def register(self, tool: Tool) -> None:
        if not TOOL_NAME_PATTERN.match(tool.name):
            raise ValueError(f"Invalid tool name {tool.name!r}: use letters, digits, '_' or '-'.")
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        """Provider-neutral schemas: {name, description, input_schema}. Adapters convert them."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_model.model_json_schema(),
            }
            for tool in self._tools.values()
        ]

    def execute(self, call: ToolCall) -> ToolResult:
        """Run one call. Never raises: every failure becomes an error result."""
        try:
            content = self._run(call)
        except ToolError as exc:
            return ToolResult(call_id=call.id, content=str(exc), is_error=True)
        except Exception as exc:  # a bug in a handler must not kill the agent
            message = f"Tool '{call.name}' crashed: {type(exc).__name__}: {exc}"
            return ToolResult(call_id=call.id, content=message, is_error=True)
        content = truncate_output(content, self.max_output_lines, self.max_output_chars)
        return ToolResult(call_id=call.id, content=content)

    def _run(self, call: ToolCall) -> str:
        tool = self._tools.get(call.name)
        if tool is None:
            available = ", ".join(self._tools) or "(none)"
            raise ToolError(f"Unknown tool '{call.name}'. Available tools: {available}.")
        if INVALID_JSON_KEY in call.arguments:
            raise ToolError(
                f"Arguments for '{call.name}' were not valid JSON: "
                f"{call.arguments[INVALID_JSON_KEY]!r}. Send a single JSON object."
            )
        try:
            args = tool.input_model.model_validate(call.arguments)
        except ValidationError as exc:
            schema = json.dumps(tool.input_model.model_json_schema())
            raise ToolError(
                f"Invalid arguments for '{call.name}': {format_validation_error(exc)}. "
                f"Expected JSON schema: {schema}"
            ) from exc
        return tool.handler(args)


def truncate_output(text: str, max_lines: int, max_chars: int) -> str:
    """Shorten long output, keeping the head *and* the tail.

    The tail matters: test runners and compilers print the summary/error last.
    The marker tells the model that something was cut, so it can narrow its
    request (e.g. read_file with offset) instead of assuming it saw everything.
    """
    lines = text.splitlines()
    if len(lines) > max_lines:
        head, tail = max_lines // 2, max_lines - max_lines // 2
        cut = len(lines) - head - tail
        lines = [*lines[:head], f"... [truncated {cut} lines] ...", *lines[-tail:]]
        text = "\n".join(lines)
    if len(text) > max_chars:
        half = max_chars // 2
        cut = len(text) - 2 * half
        text = f"{text[:half]}\n... [truncated {cut} chars] ...\n{text[-half:]}"
    return text
