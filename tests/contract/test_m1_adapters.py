"""Contract tests for the provider adapters (M1).

Each adapter is driven through the public `LLMClient.complete()` only. The SDK is
replaced by a small stub that returns objects in the *real SDK format*
(`openai.types.responses.Response`, `anthropic.types.Message`), so these tests
check the translation without any network access.

Contract for your own adapters:
- constructors: `OpenAIClient(model, *, api_key=None, sdk=None)` and
  `AnthropicClient(model, *, api_key=None, sdk=None)`;
- non-streaming calls use `sdk.responses.create(...)` / `sdk.messages.create(...)`;
- with `on_text`, they use `sdk.responses.stream(...)` / `sdk.messages.stream(...)`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic.types
import openai.types.responses
import pytest

from minicode.llm.anthropic_client import AnthropicClient
from minicode.llm.base import LLMClient
from minicode.llm.openai_client import OpenAIClient
from minicode.llm.types import LLMResponse, Message, ToolCall, ToolResult

pytestmark = pytest.mark.m1

HISTORY = [
    Message.user("Read a.py"),
    Message(
        role="assistant",
        content="Reading.",
        tool_calls=[ToolCall(id="call_1", name="read_file", arguments={"path": "a.py"})],
    ),
    Message.tool([ToolResult(call_id="call_1", content="print('hi')")]),
]
TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
    }
]


# --- OpenAI Responses stub ----------------------------------------------------


def openai_response(output: list[dict[str, Any]]) -> openai.types.responses.Response:
    return openai.types.responses.Response.model_validate(
        {
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
                "input_tokens": 20,
                "output_tokens": 8,
                "total_tokens": 28,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
    )


def openai_text(text: str) -> openai.types.responses.Response:
    return openai_response(
        [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ]
    )


def openai_tool_call() -> openai.types.responses.Response:
    return openai_response(
        [
            {
                "type": "function_call",
                "call_id": "call_2",
                "name": "read_file",
                "arguments": '{"path": "b.py"}',
            }
        ]
    )


class OpenAIStreamStub:
    def __init__(self, final: openai.types.responses.Response) -> None:
        self.final = final

    def __enter__(self) -> OpenAIStreamStub:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def __iter__(self) -> Any:
        text = self.final.output_text
        half = len(text) // 2
        yield SimpleNamespace(type="response.created")
        for chunk in (text[:half], text[half:]):
            yield SimpleNamespace(type="response.output_text.delta", delta=chunk)
        yield SimpleNamespace(type="response.completed")

    def get_final_response(self) -> openai.types.responses.Response:
        return self.final


class OpenAISDKStub:
    def __init__(self, response: openai.types.responses.Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = self

    def create(self, **kwargs: Any) -> openai.types.responses.Response:
        self.calls.append(("create", kwargs))
        return self.response

    def stream(self, **kwargs: Any) -> OpenAIStreamStub:
        self.calls.append(("stream", kwargs))
        return OpenAIStreamStub(self.response)


# --- Anthropic Messages stub --------------------------------------------------


def anthropic_message(content: list[dict[str, Any]], stop_reason: str) -> anthropic.types.Message:
    return anthropic.types.Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": content,
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 20, "output_tokens": 8},
        }
    )


def anthropic_text(text: str) -> anthropic.types.Message:
    return anthropic_message([{"type": "text", "text": text}], "end_turn")


def anthropic_tool_call() -> anthropic.types.Message:
    block = {"type": "tool_use", "id": "call_2", "name": "read_file", "input": {"path": "b.py"}}
    return anthropic_message([block], "tool_use")


class AnthropicStreamStub:
    def __init__(self, final: anthropic.types.Message) -> None:
        self.final = final
        text = "".join(b.text for b in final.content if b.type == "text")
        half = len(text) // 2
        self.text_stream = iter([text[:half], text[half:]])

    def __enter__(self) -> AnthropicStreamStub:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_final_message(self) -> anthropic.types.Message:
        return self.final


class AnthropicSDKStub:
    def __init__(self, message: anthropic.types.Message) -> None:
        self.message = message
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> anthropic.types.Message:
        self.calls.append(("create", kwargs))
        return self.message

    def stream(self, **kwargs: Any) -> AnthropicStreamStub:
        self.calls.append(("stream", kwargs))
        return AnthropicStreamStub(self.message)


# --- Shared contract, run against both adapters -------------------------------


def make_client(provider: str, kind: str) -> tuple[LLMClient, Any]:
    """Return (adapter, sdk_stub) where the stub replies with a `kind` turn."""
    if provider == "openai":
        reply = openai_text("Hello world") if kind == "text" else openai_tool_call()
        openai_sdk = OpenAISDKStub(reply)
        return OpenAIClient("gpt-test", sdk=openai_sdk), openai_sdk  # type: ignore[arg-type]
    message = anthropic_text("Hello world") if kind == "text" else anthropic_tool_call()
    anthropic_sdk = AnthropicSDKStub(message)
    return AnthropicClient("claude-test", sdk=anthropic_sdk), anthropic_sdk  # type: ignore[arg-type]


PROVIDERS = ["openai", "anthropic"]


def complete(client: LLMClient, **kwargs: Any) -> LLMResponse:
    return client.complete(HISTORY, system="sys", tools=TOOLS, max_tokens=100, **kwargs)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_text_reply(provider: str) -> None:
    client, _ = make_client(provider, "text")
    result = complete(client)
    assert result.text == "Hello world"
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (20, 8)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_tool_call_reply(provider: str) -> None:
    client, _ = make_client(provider, "tool")
    result = complete(client)
    assert result.stop_reason == "tool_use"
    assert result.tool_calls == [
        ToolCall(id="call_2", name="read_file", arguments={"path": "b.py"})
    ]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_streaming_delivers_chunks_and_same_result(provider: str) -> None:
    client, sdk = make_client(provider, "text")
    chunks: list[str] = []
    result = complete(client, on_text=chunks.append)
    assert len(chunks) > 1
    assert "".join(chunks) == "Hello world" == result.text
    assert sdk.calls[0][0] == "stream"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_without_on_text_no_streaming(provider: str) -> None:
    client, sdk = make_client(provider, "text")
    complete(client)
    assert sdk.calls[0][0] == "create"


def test_openai_wire_format() -> None:
    client, sdk = make_client("openai", "text")
    complete(client)
    sent = sdk.calls[0][1]
    assert sent["instructions"] == "sys"
    assert sent["store"] is False
    assert sent["tools"][0]["type"] == "function"
    assert sent["input"][-1] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "print('hi')",
    }


def test_anthropic_wire_format() -> None:
    client, sdk = make_client("anthropic", "text")
    complete(client)
    sent = sdk.calls[0][1]
    assert sent["system"] == "sys"
    assert sent["tools"][0]["input_schema"]["type"] == "object"
    # Anthropic has no tool role: results go back inside a *user* message.
    assert sent["messages"][-1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": "print('hi')",
                "is_error": False,
            }
        ],
    }
