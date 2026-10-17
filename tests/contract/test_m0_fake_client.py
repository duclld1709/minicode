"""Contract tests for FakeLLMClient and the LLMClient Protocol."""

import pytest

from minicode.llm.base import LLMClient
from minicode.llm.fake_client import FakeLLMClient
from minicode.llm.types import LLMResponse, Message, ToolCall, Usage

pytestmark = pytest.mark.m0


def _complete(client: FakeLLMClient, text: str = "hello") -> LLMResponse:
    return client.complete(
        [Message(role="user", content=text)], system="sys", tools=[], max_tokens=100
    )


def test_fake_client_satisfies_protocol() -> None:
    assert isinstance(FakeLLMClient(script=[]), LLMClient)


def test_returns_scripted_responses_in_order() -> None:
    client = FakeLLMClient(script=["first", "second"])
    assert _complete(client).text == "first"
    assert _complete(client).text == "second"


def test_string_entries_are_final_text_answers() -> None:
    response = _complete(FakeLLMClient(script=["done"]))
    assert response.tool_calls == []
    assert response.stop_reason == "end_turn"


def test_full_llm_responses_pass_through() -> None:
    scripted = LLMResponse(
        text="",
        tool_calls=[ToolCall(id="c1", name="list_dir", arguments={})],
        stop_reason="tool_use",
        usage=Usage(input_tokens=3, output_tokens=4),
    )
    assert _complete(FakeLLMClient(script=[scripted])) == scripted


def test_records_what_was_sent() -> None:
    client = FakeLLMClient(script=["ok"])
    _complete(client, text="question")
    call = client.calls[0]
    assert call.system == "sys"
    assert call.max_tokens == 100
    assert [m.content for m in call.messages] == ["question"]


def test_raises_when_script_is_exhausted() -> None:
    client = FakeLLMClient(script=["only one"])
    _complete(client)
    with pytest.raises(RuntimeError):
        _complete(client)


def test_on_text_receives_the_text() -> None:
    chunks: list[str] = []
    client = FakeLLMClient(script=["streamed"])
    client.complete(
        [Message(role="user", content="hi")],
        system="",
        tools=[],
        max_tokens=10,
        on_text=chunks.append,
    )
    assert "".join(chunks) == "streamed"
