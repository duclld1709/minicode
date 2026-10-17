"""Provider-neutral message types.

Every adapter translates *to* and *from* these types, so the rest of minicode
(agent loop, tools, tests) never touches an SDK-specific object. This is the
single most important seam in the project: swap the adapter, keep everything else.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

INVALID_JSON_KEY = "__invalid_json__"
"""Set in ToolCall.arguments when the model emitted arguments that are not valid JSON.

Adapters keep the raw string under this key instead of raising, so the tool
registry can return a helpful error to the model rather than crashing the agent.
"""


class ToolCall(BaseModel):
    """A tool invocation *proposed* by the model. Our code decides whether to run it."""

    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    """What we send back for one ToolCall. `call_id` links it to `ToolCall.id`."""

    call_id: str
    content: str
    is_error: bool = False


class Usage(BaseModel):
    """Token counts reported by the provider for one call (or summed over many)."""

    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        # Summing lets a session keep a running total with `total += resp.usage`.
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMResponse(BaseModel):
    """One model turn, normalized.

    `stop_reason` is normalized to a small vocabulary so callers can branch on it
    without knowing the provider: "end_turn", "tool_use", "max_tokens", or "other".
    """

    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str
    usage: Usage


Role = Literal["user", "assistant", "tool"]


class Message(BaseModel):
    """One entry in the conversation history.

    Design: a flat message with optional lists instead of a list of typed "content
    blocks". It is easier to read and covers what an agent needs:

    - role="user":      `content` holds the user's text.
    - role="assistant": `content` holds the text, `tool_calls` the proposed calls.
    - role="tool":      `tool_results` holds the results for the previous assistant
                        message's tool calls (one "tool" message per assistant turn).

    Adapters map this onto each provider's wire format (e.g. Anthropic wants tool
    results inside a "user" message; OpenAI Responses wants `function_call_output` items).
    """

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role="user", content=text)

    @classmethod
    def assistant(cls, response: LLMResponse) -> Message:
        """Store the model's turn exactly as returned, so the next call can resend it."""
        return cls(role="assistant", content=response.text, tool_calls=list(response.tool_calls))

    @classmethod
    def tool(cls, results: list[ToolResult]) -> Message:
        return cls(role="tool", tool_results=list(results))
