"""Contract tests for Agent.run() and its stopping conditions (M3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel

from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.loop import Agent
from minicode.llm.fake_client import FakeLLMClient, text_response, tool_call_response
from minicode.llm.pricing import Price
from minicode.llm.types import LLMResponse, Message, ToolCall, Usage
from minicode.tools.base import Tool, ToolRegistry

pytestmark = pytest.mark.m3


class TextArgs(BaseModel):
    text: str = ""


def make_registry(handler: Callable[[TextArgs], str] | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool("echo", "Echo.", TextArgs, handler or (lambda a: f"echo:{a.text}"), "read")
    )
    return registry


def echo_call(call_id: str, text: str = "x") -> ToolCall:
    return ToolCall(id=call_id, name="echo", arguments={"text": text})


def make_agent(script: list[LLMResponse | str], **kwargs: Any) -> tuple[Agent, FakeLLMClient]:
    llm = FakeLLMClient(script=script)
    guards = kwargs.pop("guards", Guards())
    registry = kwargs.pop("registry", make_registry())
    return Agent(llm, registry, guards, permission=PermissionPolicy(mode="auto"), **kwargs), llm


def looping_script(n: int = 20, usage: Usage | None = None) -> list[LLMResponse | str]:
    """A model that never stops calling tools."""
    return [tool_call_response([echo_call(f"c{i}")], usage=usage) for i in range(n)]


# --- Normal completion -------------------------------------------------------------


def test_completes_when_model_stops_calling_tools() -> None:
    agent, _ = make_agent(["All done."])
    result = agent.run("say hi")
    assert (result.final_text, result.steps, result.stop_reason) == ("All done.", 1, "completed")


def test_tool_results_are_fed_back_to_the_model() -> None:
    agent, llm = make_agent([tool_call_response([echo_call("c1", "hi")]), "It said echo:hi"])
    result = agent.run("echo hi")
    assert result.steps == 2
    sent = llm.calls[1].messages
    assert [m.role for m in sent] == ["user", "assistant", "tool"]
    # `in`, not `==`: from M5 on, results are wrapped in <tool_output> tags.
    assert "echo:hi" in sent[-1].tool_results[0].content
    assert llm.calls[0].tools[0]["name"] == "echo"  # tool schemas are sent


def test_multiple_calls_in_one_turn_keep_their_order() -> None:
    calls = [echo_call("a", "1"), echo_call("b", "2"), echo_call("c", "3")]
    agent, llm = make_agent([tool_call_response(calls), "ok"])
    agent.run("go")
    results = llm.calls[1].messages[-1].tool_results
    assert [r.call_id for r in results] == ["a", "b", "c"]
    for result, expected in zip(results, ["echo:1", "echo:2", "echo:3"], strict=True):
        assert expected in result.content


def test_usage_is_summed_over_steps() -> None:
    usage = Usage(input_tokens=100, output_tokens=10)
    agent, _ = make_agent(
        [tool_call_response([echo_call("c1")], usage=usage), text_response("ok", usage)]
    )
    assert agent.run("go").usage == Usage(input_tokens=200, output_tokens=20)


def test_history_continues_across_runs() -> None:
    agent, llm = make_agent(["first answer", "second answer"])
    agent.run("task one")
    agent.run("task two")
    assert [m.content for m in llm.calls[1].messages] == ["task one", "first answer", "task two"]


def test_truncated_output_is_reported() -> None:
    cut = LLMResponse(text="partial", stop_reason="max_tokens", usage=Usage())
    agent, _ = make_agent([cut])
    assert agent.run("go").stop_reason == "output_truncated"


# --- Stopping conditions -------------------------------------------------------------


def test_max_steps() -> None:
    agent, llm = make_agent(looping_script(), guards=Guards(max_steps=3))
    result = agent.run("loop forever")
    assert (result.stop_reason, result.steps, len(llm.calls)) == ("max_steps", 3, 3)


def test_token_budget() -> None:
    usage = Usage(input_tokens=90, output_tokens=10)
    agent, _ = make_agent(looping_script(usage=usage), guards=Guards(max_total_tokens=250))
    result = agent.run("go")
    assert (result.stop_reason, result.steps) == ("token_budget", 3)


def test_cost_budget() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=0)  # $1 per step at the price below
    agent, _ = make_agent(
        looping_script(usage=usage),
        guards=Guards(max_cost_usd=2.5),
        prices={"fake-model": Price(input_per_mtok=1.0, output_per_mtok=0.0)},
    )
    result = agent.run("go")
    assert (result.stop_reason, result.steps) == ("cost_budget", 3)
    assert result.cost == pytest.approx(3.0)


def test_wall_time() -> None:
    now = [0.0]

    def clock() -> float:
        now[0] += 10.0  # every look at the clock is 10 seconds later
        return now[0]

    agent, _ = make_agent(looping_script(), guards=Guards(max_wall_seconds=25), clock=clock)
    assert agent.run("go").stop_reason == "wall_time"


# --- Ctrl+C ---------------------------------------------------------------------------


class InterruptingLLM(FakeLLMClient):
    """Raises KeyboardInterrupt on call number `at` (1-based)."""

    def __init__(self, script: list[LLMResponse | str], at: int) -> None:
        super().__init__(script=script)
        self.at = at

    def complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        if len(self.calls) + 1 == self.at:
            raise KeyboardInterrupt
        return super().complete(messages, **kwargs)


def test_ctrl_c_during_llm_call_stops_gracefully() -> None:
    llm = InterruptingLLM([tool_call_response([echo_call("c1")]), "never"], at=2)
    agent = Agent(llm, make_registry(), Guards(), permission=PermissionPolicy(mode="auto"))
    result = agent.run("go")
    assert (result.stop_reason, result.steps) == ("interrupted", 1)
    assert [m.role for m in agent.history] == ["user", "assistant", "tool"]


def test_ctrl_c_during_tools_keeps_history_valid() -> None:
    def handler(args: TextArgs) -> str:
        if args.text == "stop":
            raise KeyboardInterrupt
        return "ran"

    calls = [echo_call("a", "ok"), echo_call("b", "stop"), echo_call("c", "never")]
    agent, _ = make_agent([tool_call_response(calls)], registry=make_registry(handler))
    result = agent.run("go")

    assert result.stop_reason == "interrupted"
    tool_message = agent.history[-1]
    assert tool_message.role == "tool"
    # every call has a result, so the next request in the session is still valid
    assert [r.call_id for r in tool_message.tool_results] == ["a", "b", "c"]
    first = tool_message.tool_results[0]
    assert not first.is_error  # the call that finished keeps its real result...
    assert "ran" in first.content and "Interrupted" not in first.content
    assert all(r.is_error for r in tool_message.tool_results[1:])
