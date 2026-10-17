"""Contract tests for the provider-neutral types (PROJECT_SPEC §3.2).

These only use the public API, so they can be copied into a learner's repo.
"""

import pytest

from minicode.llm.types import LLMResponse, Message, ToolCall, ToolResult, Usage

pytestmark = pytest.mark.m0


def test_tool_call_fields() -> None:
    call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
    assert (call.id, call.name, call.arguments) == ("c1", "read_file", {"path": "a.py"})


def test_tool_result_defaults_to_not_error() -> None:
    result = ToolResult(call_id="c1", content="ok")
    assert result.is_error is False


def test_usage_can_be_summed() -> None:
    total = Usage(input_tokens=10, output_tokens=2) + Usage(input_tokens=5, output_tokens=3)
    assert (total.input_tokens, total.output_tokens) == (15, 5)


def test_llm_response_fields() -> None:
    response = LLMResponse(
        text="hi",
        tool_calls=[],
        stop_reason="end_turn",
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    assert response.text == "hi"
    assert response.tool_calls == []


@pytest.mark.parametrize("role", ["user", "assistant", "tool"])
def test_message_accepts_the_three_roles(role: str) -> None:
    assert Message(role=role).role == role  # type: ignore[arg-type]


def test_message_rejects_unknown_role() -> None:
    with pytest.raises(ValueError):
        Message(role="system")  # type: ignore[arg-type]
