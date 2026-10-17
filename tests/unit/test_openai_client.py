"""Tests for the OpenAI Responses adapter, using objects in the real SDK format."""

from typing import Any

import pytest
from openai.types.responses import Response

from minicode.llm.openai_client import (
    INVALID_JSON_KEY,
    OpenAIClient,
    from_response,
    to_function_tool,
    to_input_items,
)
from minicode.llm.types import Message, ToolCall, ToolResult

pytestmark = pytest.mark.m0


def make_response(output: list[dict[str, Any]], **overrides: Any) -> Response:
    """Build a Response exactly as the SDK would parse it from JSON."""
    data: dict[str, Any] = {
        "id": "resp_1",
        "created_at": 0,
        "model": "gpt-test",
        "object": "response",
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "status": "completed",
        "usage": {
            "input_tokens": 12,
            "output_tokens": 7,
            "total_tokens": 19,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }
    data.update(overrides)
    return Response.model_validate(data)


def text_item(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def call_item(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments}


def test_text_response_is_normalized() -> None:
    result = from_response(make_response([text_item("Hello!")]))
    assert result.text == "Hello!"
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (12, 7)


def test_function_calls_become_tool_calls() -> None:
    response = make_response([call_item("call_1", "read_file", '{"path": "a.py"}')])
    result = from_response(response)
    assert result.stop_reason == "tool_use"
    assert result.tool_calls == [
        ToolCall(id="call_1", name="read_file", arguments={"path": "a.py"})
    ]


def test_invalid_json_arguments_are_kept_not_raised() -> None:
    result = from_response(make_response([call_item("call_1", "read_file", "{not json")]))
    assert result.tool_calls[0].arguments == {INVALID_JSON_KEY: "{not json"}


def test_truncated_output_maps_to_max_tokens() -> None:
    response = make_response(
        [text_item("partial")],
        status="incomplete",
        incomplete_details={"reason": "max_output_tokens"},
    )
    assert from_response(response).stop_reason == "max_tokens"


def test_history_is_flattened_to_input_items() -> None:
    history = [
        Message.user("fix it"),
        Message(
            role="assistant",
            content="Looking.",
            tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})],
        ),
        Message.tool([ToolResult(call_id="c1", content="boom", is_error=True)]),
    ]
    assert to_input_items(history) == [
        {"role": "user", "content": "fix it"},
        {"role": "assistant", "content": "Looking."},
        {
            "type": "function_call",
            "call_id": "c1",
            "name": "read_file",
            "arguments": '{"path": "a.py"}',
        },
        {"type": "function_call_output", "call_id": "c1", "output": "ERROR: boom"},
    ]


def test_neutral_tool_schema_converts_to_function_tool() -> None:
    schema = {"name": "t", "description": "d", "input_schema": {"type": "object"}}
    assert to_function_tool(schema) == {
        "type": "function",
        "name": "t",
        "description": "d",
        "parameters": {"type": "object"},
        "strict": False,
    }


class StubResponses:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Response:
        self.kwargs = kwargs
        return self.response


class StubSDK:
    def __init__(self, response: Response) -> None:
        self.responses = StubResponses(response)


def test_complete_sends_stateless_request() -> None:
    sdk = StubSDK(make_response([text_item("hi")]))
    client = OpenAIClient("gpt-test", sdk=sdk)  # type: ignore[arg-type]
    chunks: list[str] = []

    result = client.complete(
        [Message.user("hello")], system="be brief", tools=[], max_tokens=50, on_text=chunks.append
    )

    sent = sdk.responses.kwargs
    assert sent["model"] == "gpt-test"
    assert sent["instructions"] == "be brief"
    assert sent["max_output_tokens"] == 50
    assert sent["store"] is False  # we resend history ourselves
    assert sent["input"] == [{"role": "user", "content": "hello"}]
    assert result.text == "hi"
    assert chunks == ["hi"]
