import pytest
from anthropic.types import Message as AnthropicMessage

from minicode.llm.anthropic_client import from_message, to_messages, to_tool
from minicode.llm.types import Message, ToolCall, ToolResult

pytestmark = pytest.mark.m1


def make_message(stop_reason: str | None, content: list[dict[str, object]]) -> AnthropicMessage:
    return AnthropicMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": content,
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


@pytest.mark.parametrize(
    ("anthropic_reason", "ours"),
    [
        ("end_turn", "end_turn"),
        ("stop_sequence", "end_turn"),
        ("tool_use", "tool_use"),
        ("max_tokens", "max_tokens"),
        ("refusal", "other"),
        (None, "other"),
    ],
)
def test_stop_reason_mapping(anthropic_reason: str | None, ours: str) -> None:
    message = make_message(anthropic_reason, [{"type": "text", "text": "x"}])
    assert from_message(message).stop_reason == ours


def test_multiple_text_blocks_are_joined() -> None:
    message = make_message(
        "end_turn", [{"type": "text", "text": "Hello "}, {"type": "text", "text": "there"}]
    )
    assert from_message(message).text == "Hello there"


def test_assistant_turn_becomes_text_and_tool_use_blocks() -> None:
    history = [
        Message(
            role="assistant",
            content="Let me look.",
            tool_calls=[ToolCall(id="t1", name="list_dir", arguments={"path": "."})],
        )
    ]
    assert to_messages(history) == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me look."},
                {"type": "tool_use", "id": "t1", "name": "list_dir", "input": {"path": "."}},
            ],
        }
    ]


def test_empty_assistant_turn_gets_placeholder_text() -> None:
    converted = to_messages([Message(role="assistant")])
    assert converted[0]["content"] == [{"type": "text", "text": "(no content)"}]


def test_error_results_keep_is_error_flag() -> None:
    converted = to_messages(
        [Message.tool([ToolResult(call_id="t1", content="no such file", is_error=True)])]
    )
    assert converted[0]["content"][0]["is_error"] is True  # type: ignore[index]


def test_tool_schema_passes_through() -> None:
    schema = {"name": "t", "description": "d", "input_schema": {"type": "object"}}
    assert to_tool(schema) == schema
