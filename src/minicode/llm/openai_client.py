"""Adapter for the OpenAI Responses API (`client.responses.create`).

Translation summary (internal -> OpenAI "input items"):

- Message(role="user")       -> {"role": "user", "content": "..."}
- Message(role="assistant")  -> {"role": "assistant", "content": "..."}
                                + one {"type": "function_call", ...} item per tool call
- Message(role="tool")       -> one {"type": "function_call_output", ...} item per result

We send `store=False` and resend the whole history every call. The API *could*
keep state server-side (`previous_response_id`), but staying stateless keeps the
mental model honest: the model only knows what is in the request.
"""

from __future__ import annotations

import json
from typing import Any

import openai
from openai.types.responses import (
    FunctionToolParam,
    Response,
    ResponseInputItemParam,
)

from minicode.llm.base import TextCallback
from minicode.llm.types import INVALID_JSON_KEY, LLMResponse, Message, ToolCall, Usage


class OpenAIClient:
    """LLMClient implementation backed by the OpenAI Responses API."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        sdk: openai.OpenAI | None = None,
    ) -> None:
        # `sdk` is injectable so tests can pass a stub instead of a real HTTP client.
        self.model = model
        self._sdk = sdk if sdk is not None else openai.OpenAI(api_key=api_key)

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
            "instructions": system,
            "input": to_input_items(messages),
            "tools": [to_function_tool(t) for t in tools] if tools else openai.omit,
            "max_output_tokens": max_tokens,
            "store": False,
        }
        if on_text is None:
            return from_response(self._sdk.responses.create(**request))
        # Streaming: the API sends many small events; we only care about text deltas.
        # The final, fully assembled Response is the same shape as the non-streaming one.
        with self._sdk.responses.stream(**request) as stream:
            for event in stream:
                if event.type == "response.output_text.delta":
                    on_text(event.delta)
            return from_response(stream.get_final_response())


def to_input_items(messages: list[Message]) -> list[ResponseInputItemParam]:
    """Flatten our history into the Responses API's list of input items."""
    items: list[ResponseInputItemParam] = []
    for message in messages:
        if message.role == "user":
            items.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            if message.content:
                items.append({"role": "assistant", "content": message.content})
            for call in message.tool_calls:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call.id,
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    }
                )
        else:
            for result in message.tool_results:
                # The Responses API has no `is_error` flag, so we say it in the text.
                output = f"ERROR: {result.content}" if result.is_error else result.content
                items.append(
                    {"type": "function_call_output", "call_id": result.call_id, "output": output}
                )
    return items


def to_function_tool(schema: dict[str, Any]) -> FunctionToolParam:
    """Convert a neutral tool schema ({name, description, input_schema}) to OpenAI's shape."""
    return {
        "type": "function",
        "name": schema["name"],
        "description": schema.get("description", ""),
        "parameters": schema["input_schema"],
        # Strict mode demands every property be required; our pydantic schemas have
        # optional fields, so we validate arguments ourselves instead (see M2).
        "strict": False,
    }


def from_response(response: Response) -> LLMResponse:
    """Normalize an OpenAI Response into our LLMResponse."""
    tool_calls = [
        ToolCall(id=item.call_id, name=item.name, arguments=_parse_arguments(item.arguments))
        for item in response.output
        if item.type == "function_call"
    ]
    usage = Usage()
    if response.usage is not None:
        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
    return LLMResponse(
        text=response.output_text,
        tool_calls=tool_calls,
        stop_reason=_stop_reason(response, has_tool_calls=bool(tool_calls)),
        usage=usage,
    )


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {INVALID_JSON_KEY: raw}
    return parsed if isinstance(parsed, dict) else {INVALID_JSON_KEY: raw}


def _stop_reason(response: Response, *, has_tool_calls: bool) -> str:
    # OpenAI has no single "stop reason" field; derive one from status + output.
    if has_tool_calls:
        return "tool_use"
    if response.status == "incomplete":
        details = response.incomplete_details
        if details is not None and details.reason == "max_output_tokens":
            return "max_tokens"
        return "other"
    if response.status == "completed":
        return "end_turn"
    return "other"
