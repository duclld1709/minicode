"""Contract tests for parallel execution of read tools (M6)."""

from __future__ import annotations

import threading
import time

import pytest
from pydantic import BaseModel

from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.loop import Agent
from minicode.llm.fake_client import FakeLLMClient, tool_call_response
from minicode.llm.types import ToolCall
from minicode.tools.base import Risk, Tool, ToolRegistry

pytestmark = pytest.mark.m6


class Args(BaseModel):
    key: str


def run_turn(registry: ToolRegistry, calls: list[ToolCall]) -> list[str]:
    """Run one turn with these calls; return the tool result contents in history order."""
    llm = FakeLLMClient(script=[tool_call_response(calls), "done"])
    agent = Agent(llm, registry, Guards(), permission=PermissionPolicy(mode="auto"))
    agent.run("go")
    return [r.content for r in agent.history[2].tool_results]


def calls_for(*keys: str, tool: str = "look") -> list[ToolCall]:
    return [ToolCall(id=k, name=tool, arguments={"key": k}) for k in keys]


def test_independent_reads_really_run_concurrently() -> None:
    # A barrier only opens when all 4 handlers are inside it at the same time.
    # Run serially, the first handler would wait alone and time out.
    barrier = threading.Barrier(4, timeout=5)

    def look(args: Args) -> str:
        barrier.wait()
        return f"saw {args.key}"

    registry = ToolRegistry()
    registry.register(Tool("look", "Look.", Args, look, "read"))
    results = run_turn(registry, calls_for("a", "b", "c", "d"))
    assert all("saw" in r for r in results)


def test_results_keep_the_order_of_the_calls() -> None:
    delays = {"a": 0.3, "b": 0.2, "c": 0.1, "d": 0.0}  # finish in reverse order

    def look(args: Args) -> str:
        time.sleep(delays[args.key])
        return f"result-{args.key}"

    registry = ToolRegistry()
    registry.register(Tool("look", "Look.", Args, look, "read"))
    results = run_turn(registry, calls_for("a", "b", "c", "d"))
    assert [r.split("result-")[1][0] for r in results] == ["a", "b", "c", "d"]


def test_non_read_calls_are_barriers_and_run_alone() -> None:
    events: list[str] = []
    lock = threading.Lock()

    def make(risk: Risk) -> Tool:
        def handler(args: Args) -> str:
            time.sleep(0.05)
            with lock:
                events.append(args.key)
            return args.key

        return Tool(f"{risk}_tool", "t", Args, handler, risk)

    registry = ToolRegistry()
    registry.register(make("read"))
    registry.register(make("write"))
    calls = [
        *calls_for("r1", "r2", tool="read_tool"),
        *calls_for("w1", tool="write_tool"),
        *calls_for("r3", tool="read_tool"),
    ]
    results = run_turn(registry, calls)

    assert set(events[:2]) == {"r1", "r2"}  # the first two reads, in either order
    assert events[2:] == ["w1", "r3"]  # the write waits for them; the last read waits for it
    assert [r.split("\n")[1] for r in results] == ["r1", "r2", "w1", "r3"]
