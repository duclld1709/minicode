"""A scripted LLM client for offline, deterministic tests.

Tests describe what the "model" will say, turn by turn, then assert on what our
code did with it. No network, no cost, no flakiness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from minicode.llm.base import TextCallback
from minicode.llm.types import LLMResponse, Message, ToolCall, Usage


@dataclass
class RecordedCall:
    """A snapshot of one `complete()` call, so tests can inspect exactly what was sent."""

    messages: list[Message]
    system: str
    tools: list[dict[str, Any]]
    max_tokens: int


class ScriptExhaustedError(RuntimeError):
    """Raised when the code under test calls the fake more times than scripted."""


@dataclass
class FakeLLMClient:
    """Returns the scripted responses in order.

    A plain `str` in the script is shorthand for a text-only final answer.
    """

    script: list[LLMResponse | str]
    model: str = "fake-model"
    calls: list[RecordedCall] = field(default_factory=list)

    def complete(
        self,
        messages: list[Message],
        *,
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
        on_text: TextCallback | None = None,
    ) -> LLMResponse:
        # Copy the history: the caller keeps mutating its list after this call returns.
        recorded = RecordedCall(
            [m.model_copy(deep=True) for m in messages], system, tools, max_tokens
        )
        self.calls.append(recorded)
        index = len(self.calls) - 1
        if index >= len(self.script):
            raise ScriptExhaustedError(
                f"FakeLLMClient was called {index + 1} times but only "
                f"{len(self.script)} responses were scripted."
            )
        response = _as_response(self.script[index])
        if on_text is not None and response.text:
            on_text(response.text)
        return response


def _as_response(item: LLMResponse | str) -> LLMResponse:
    if isinstance(item, LLMResponse):
        return item
    return text_response(item)


def text_response(text: str, usage: Usage | None = None) -> LLMResponse:
    """Build a final, text-only turn."""
    return LLMResponse(
        text=text,
        tool_calls=[],
        stop_reason="end_turn",
        usage=usage or Usage(input_tokens=10, output_tokens=5),
    )


def tool_call_response(
    calls: list[ToolCall], text: str = "", usage: Usage | None = None
) -> LLMResponse:
    """Build a turn where the model asks for one or more tool calls."""
    return LLMResponse(
        text=text,
        tool_calls=calls,
        stop_reason="tool_use",
        usage=usage or Usage(input_tokens=10, output_tokens=5),
    )
