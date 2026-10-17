"""Contract tests for context compaction (M5)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from minicode.agent.context import Compactor, estimate_tokens
from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.loop import Agent
from minicode.llm.fake_client import FakeLLMClient, text_response, tool_call_response
from minicode.llm.types import LLMResponse, Message, ToolCall, ToolResult, Usage
from minicode.tools.base import Tool, ToolRegistry

pytestmark = pytest.mark.m5

TASK = "Fix the failing tests in calculator/"


def step(i: int, result: str) -> list[Message]:
    """One agent step: assistant asks for a tool, tool answers."""
    call = ToolCall(id=f"c{i}", name="read_file", arguments={"path": f"f{i}.py"})
    return [
        Message(role="assistant", content=f"step {i}", tool_calls=[call]),
        Message.tool([ToolResult(call_id=f"c{i}", content=result)]),
    ]


def history(steps: int, result_chars: int) -> list[Message]:
    messages = [Message.user(TASK)]
    for i in range(steps):
        messages += step(i, "x" * result_chars)
    return messages


def assert_valid(messages: list[Message]) -> None:
    """Every tool call is followed by its results; the history starts with a user turn."""
    assert messages[0].role == "user"
    for i, message in enumerate(messages):
        if message.tool_calls:
            results = messages[i + 1].tool_results
            assert [r.call_id for r in results] == [c.id for c in message.tool_calls]


def test_estimate_is_chars_over_four() -> None:
    assert estimate_tokens([Message.user("x" * 400)], system="y" * 400) == 200


def test_below_threshold_nothing_happens() -> None:
    small = FakeLLMClient(script=[])
    messages = history(steps=10, result_chars=100)
    compaction = Compactor(small, threshold_tokens=10_000).maybe_compact(messages)
    assert compaction.messages is messages
    assert not compaction.changed
    assert small.calls == []


def test_stage_one_clears_old_long_tool_results() -> None:
    small = FakeLLMClient(script=[])
    messages = history(steps=10, result_chars=5_000)  # ~12.5k tokens
    compactor = Compactor(
        small, threshold_tokens=10_000, keep_last_steps=3, clear_results_over_chars=1_000
    )
    compaction = compactor.maybe_compact(messages)

    assert compaction.cleared_results == 7  # steps 0..6; the last 3 steps are untouched
    assert compaction.summarized_messages == 0
    assert small.calls == []  # clearing was enough: no summary call
    assert "cleared to save context" in compaction.messages[2].tool_results[0].content
    assert compaction.messages[-1].tool_results[0].content == "x" * 5_000
    assert estimate_tokens(compaction.messages) < 10_000
    assert_valid(compaction.messages)


def test_stage_two_summarizes_with_small_model() -> None:
    small = FakeLLMClient(
        script=[
            text_response("Read f0..f6; bug is in add().", Usage(input_tokens=50, output_tokens=20))
        ]
    )
    messages = history(steps=10, result_chars=500)  # short results: clearing cannot help
    compactor = Compactor(
        small, threshold_tokens=1_000, keep_last_steps=3, clear_results_over_chars=1_000
    )
    compaction = compactor.maybe_compact(messages)

    assert len(small.calls) == 1
    summary, *recent = compaction.messages
    assert summary.role == "user"
    assert "bug is in add()" in summary.content
    assert TASK in summary.content  # the original request survives verbatim
    assert [m.content for m in recent if m.role == "assistant"] == ["step 7", "step 8", "step 9"]
    assert compaction.usage == Usage(input_tokens=50, output_tokens=20)
    assert_valid(compaction.messages)


def test_recent_steps_are_never_touched() -> None:
    small = FakeLLMClient(script=[])
    messages = history(steps=3, result_chars=50_000)
    compaction = Compactor(small, threshold_tokens=1_000, keep_last_steps=6).maybe_compact(messages)
    assert not compaction.changed  # all steps are "recent"


def test_failed_summary_falls_back_to_cleared_history() -> None:
    small = FakeLLMClient(script=[])  # any call raises
    messages = history(steps=10, result_chars=500)
    compaction = Compactor(small, threshold_tokens=1_000, keep_last_steps=3).maybe_compact(messages)
    assert compaction.summarized_messages == 0
    assert len(compaction.messages) == len(messages)


# --- inside the agent loop --------------------------------------------------------------------


class PathArgs(BaseModel):
    path: str = ""


class Notices:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def on_text(self, chunk: str) -> None: ...
    def on_tool_call(self, call: ToolCall) -> None: ...
    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None: ...

    def on_notice(self, message: str) -> None:
        self.messages.append(message)


def test_agent_compacts_during_a_long_task() -> None:
    registry = ToolRegistry()
    registry.register(Tool("read_file", "Read.", PathArgs, lambda a: "y" * 4_000, "read"))
    calls: list[LLMResponse | str] = [
        tool_call_response([ToolCall(id=f"c{i}", name="read_file", arguments={"path": "a"})])
        for i in range(8)
    ]
    llm = FakeLLMClient(script=[*calls, "done"])
    notices = Notices()
    compactor = Compactor(
        FakeLLMClient(script=[]),
        threshold_tokens=3_000,
        keep_last_steps=2,
        clear_results_over_chars=1_000,
    )
    agent = Agent(
        llm,
        registry,
        Guards(),
        permission=PermissionPolicy(mode="auto"),
        listener=notices,
        compactor=compactor,
    )

    result = agent.run(TASK)

    assert result.stop_reason == "completed"
    assert notices.messages, "compaction should have been reported"
    last_request = llm.calls[-1].messages
    assert estimate_tokens(last_request) < 3_000 + 2_000  # stayed near the threshold
    assert_valid(agent.history)
