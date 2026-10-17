"""Contract tests for Tool / ToolRegistry (M2)."""

import pytest
from pydantic import BaseModel, Field

from minicode.llm.fake_client import FakeLLMClient, tool_call_response
from minicode.llm.types import INVALID_JSON_KEY, Message, ToolCall
from minicode.tools.base import Tool, ToolError, ToolRegistry

pytestmark = pytest.mark.m2


class EchoArgs(BaseModel):
    text: str = Field(description="Text to echo back.")
    times: int = 1


def echo(args: EchoArgs) -> str:
    return args.text * args.times


def make_registry(**limits: int) -> ToolRegistry:
    registry = ToolRegistry(**limits)
    registry.register(Tool("echo", "Echo text.", EchoArgs, echo, "read"))
    return registry


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=arguments)


def test_schema_is_generated_from_the_input_model() -> None:
    [schema] = make_registry().schemas()
    assert schema["name"] == "echo"
    assert schema["description"] == "Echo text."
    properties = schema["input_schema"]["properties"]
    assert properties["text"]["description"] == "Text to echo back."
    assert schema["input_schema"]["required"] == ["text"]


def test_successful_call() -> None:
    result = make_registry().execute(call("echo", text="ab", times=2))
    assert (result.call_id, result.content, result.is_error) == ("c1", "abab", False)


def test_unknown_tool_lists_available_tools() -> None:
    result = make_registry().execute(call("ech0", text="x"))
    assert result.is_error
    assert "echo" in result.content


def test_arguments_failing_the_schema() -> None:
    result = make_registry().execute(call("echo", times="many"))
    assert result.is_error
    assert "text" in result.content  # missing field is named
    assert "times" in result.content  # wrong type is named


def test_arguments_that_were_not_json() -> None:
    result = make_registry().execute(call("echo", **{INVALID_JSON_KEY: "{oops"}))
    assert result.is_error
    assert "JSON" in result.content


def test_handler_exception_never_escapes() -> None:
    def broken(args: EchoArgs) -> str:
        raise RuntimeError("disk on fire")

    registry = ToolRegistry()
    registry.register(Tool("broken", "Always fails.", EchoArgs, broken, "read"))
    result = registry.execute(call("broken", text="x"))
    assert result.is_error
    assert "disk on fire" in result.content


def test_tool_error_message_is_passed_through() -> None:
    def picky(args: EchoArgs) -> str:
        raise ToolError("Say please.")

    registry = ToolRegistry()
    registry.register(Tool("picky", "Picky.", EchoArgs, picky, "read"))
    result = registry.execute(call("picky", text="x"))
    assert (result.content, result.is_error) == ("Say please.", True)


def test_long_output_is_truncated_keeping_head_and_tail() -> None:
    registry = make_registry(max_output_lines=10)
    result = registry.execute(call("echo", text="line\n", times=100))
    assert not result.is_error
    lines = result.content.splitlines()
    assert "[truncated 90 lines]" in result.content
    assert lines[0] == "line" and lines[-1] == "line"
    assert len(lines) == 11


def test_duplicate_tool_names_are_rejected() -> None:
    registry = make_registry()
    with pytest.raises(ValueError):
        registry.register(Tool("echo", "Again.", EchoArgs, echo, "read"))


def test_one_tool_use_turn_with_fake_llm() -> None:
    """The full M2 flow: model proposes -> we execute -> result goes back -> model answers."""
    registry = make_registry()
    llm = FakeLLMClient(
        script=[tool_call_response([call("echo", text="hi", times=3)]), "The tool said hihihi."]
    )
    history = [Message.user("Echo hi three times.")]

    first = llm.complete(history, system="", tools=registry.schemas(), max_tokens=100)
    history.append(Message.assistant(first))
    history.append(Message.tool([registry.execute(c) for c in first.tool_calls]))
    final = llm.complete(history, system="", tools=registry.schemas(), max_tokens=100)

    assert final.text == "The tool said hihihi."
    sent_back = llm.calls[1].messages[-1]
    assert sent_back.role == "tool"
    assert sent_back.tool_results[0].content == "hihihi"
    assert llm.calls[0].tools[0]["name"] == "echo"
