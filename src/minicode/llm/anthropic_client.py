"""Adapter for the Anthropic Messages API (`client.messages.create` / `.stream`).

Translation summary (internal -> Anthropic messages):

- Message(role="user")       -> {"role": "user", "content": "..."}
- Message(role="assistant")  -> {"role": "assistant", "content": [text block, tool_use blocks...]}
- Message(role="tool")       -> {"role": "user", "content": [tool_result blocks...]}

Anthropic has no "tool" role: tool results travel inside a *user* message, all
results for one assistant turn together. The API is stateless, like OpenAI's.
"""

from __future__ import annotations

from typing import Any

import anthropic
from anthropic.types import (
    ContentBlockParam,
    MessageParam,
    ToolParam,
)
from anthropic.types import (
    Message as AnthropicMessage,
)

from minicode.llm.base import TextCallback
from minicode.llm.types import LLMResponse, Message, ToolCall, Usage

STOP_REASONS = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
}
"""Anthropic stop reasons we map onto our vocabulary; anything else becomes "other"."""


class AnthropicClient:
    """LLMClient implementation backed by the Anthropic Messages API."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        sdk: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self._sdk = sdk if sdk is not None else anthropic.Anthropic(api_key=api_key)

    def complete(
        self,
        messages: list[Message],
        *,
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
        on_text: TextCallback | None = None,
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": to_messages(messages),
            "tools": [to_tool(t) for t in tools] if tools else anthropic.omit,
            "max_tokens": max_tokens,
        }
        if on_text is None:
            return from_message(self._sdk.messages.create(**request))
        # Streaming: hand each text delta to the caller as it arrives, then build
        # the normal response from the fully assembled final message.
        with self._sdk.messages.stream(**request) as stream:
            for text in stream.text_stream:
                on_text(text)
            return from_message(stream.get_final_message())


def to_messages(messages: list[Message]) -> list[MessageParam]:
    """Convert our history into Anthropic's alternating user/assistant messages."""
    converted: list[MessageParam] = []
    for message in messages:
        if message.role == "user":
            converted.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            converted.append({"role": "assistant", "content": _assistant_blocks(message)})
        else:
            results: list[ContentBlockParam] = [
                {
                    "type": "tool_result",
                    "tool_use_id": r.call_id,
                    "content": r.content,
                    "is_error": r.is_error,
                }
                for r in message.tool_results
            ]
            converted.append({"role": "user", "content": results})
    return converted


def _assistant_blocks(message: Message) -> list[ContentBlockParam]:
    blocks: list[ContentBlockParam] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    for call in message.tool_calls:
        blocks.append(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
        )
    if not blocks:
        # The API rejects empty content; this only happens if a model returned nothing.
        blocks.append({"type": "text", "text": "(no content)"})
    return blocks


def to_tool(schema: dict[str, Any]) -> ToolParam:
    """Our neutral tool schema already matches Anthropic's shape."""
    return {
        "name": schema["name"],
        "description": schema.get("description", ""),
        "input_schema": schema["input_schema"],
    }


def from_message(message: AnthropicMessage) -> LLMResponse:
    """Normalize an Anthropic Message into our LLMResponse."""
    texts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in message.content:
        if block.type == "text":
            texts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))
    return LLMResponse(
        text="".join(texts),
        tool_calls=tool_calls,
        stop_reason=STOP_REASONS.get(message.stop_reason or "", "other"),
        usage=Usage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        ),
    )
