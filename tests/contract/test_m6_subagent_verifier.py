"""Contract tests for orchestrator-workers (delegate) and evaluator-optimizer (--verify) (M6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.loop import Agent
from minicode.llm.fake_client import FakeLLMClient, text_response, tool_call_response
from minicode.llm.types import LLMResponse, ToolCall, Usage
from minicode.tools.base import ToolRegistry
from minicode.workflows.subagent import DelegateTool
from minicode.workflows.verifier import run_with_verification

pytestmark = pytest.mark.m6

READ_ONLY = {"read_file", "list_dir", "glob", "grep"}


# --- delegate ------------------------------------------------------------------------------


def delegate_setup(
    tmp_path: Path, sub_script: list[LLMResponse | str]
) -> tuple[Agent, FakeLLMClient, FakeLLMClient]:
    (tmp_path / "config.py").write_text("def parse_config():\n    raise ValueError('bad')\n")
    sub_llm = FakeLLMClient(script=sub_script)
    delegate = DelegateTool(sub_llm, tmp_path)
    registry = ToolRegistry()
    registry.register(delegate.tool())
    ask = ToolCall(id="d1", name="delegate", arguments={"task": "How does parse_config fail?"})
    main_llm = FakeLLMClient(script=[tool_call_response([ask]), "It raises ValueError."])
    agent = Agent(main_llm, registry, Guards(), permission=PermissionPolicy())
    delegate.on_usage = agent.add_usage
    return agent, main_llm, sub_llm


def test_subagent_has_its_own_context_and_reports_back(tmp_path: Path) -> None:
    read = ToolCall(id="s1", name="read_file", arguments={"path": "config.py"})
    agent, main_llm, sub_llm = delegate_setup(
        tmp_path, [tool_call_response([read]), "parse_config raises ValueError (config.py:2)."]
    )
    result = agent.run("Investigate config errors")

    assert result.stop_reason == "completed"
    report = main_llm.calls[1].messages[-1].tool_results[0].content
    assert "parse_config raises ValueError (config.py:2)." in report
    # The orchestrator never saw the file dump: only the report.
    assert all(
        "raise ValueError('bad')" not in r.content for m in agent.history for r in m.tool_results
    )
    # The worker started from a clean history with just its task.
    assert [m.content for m in sub_llm.calls[0].messages] == ["How does parse_config fail?"]


def test_subagent_only_gets_read_only_tools(tmp_path: Path) -> None:
    agent, _, sub_llm = delegate_setup(tmp_path, ["nothing to see"])
    agent.run("go")
    assert {t["name"] for t in sub_llm.calls[0].tools} == READ_ONLY


def test_subagent_usage_counts_toward_the_parent(tmp_path: Path) -> None:
    agent, _, _ = delegate_setup(
        tmp_path, [text_response("report", Usage(input_tokens=1000, output_tokens=100))]
    )
    result = agent.run("go")
    # parent: 2 calls x (10 in, 5 out) + subagent: 1000 in, 100 out
    assert result.usage == Usage(input_tokens=1020, output_tokens=110)


def test_subagent_that_hits_its_limit_says_so(tmp_path: Path) -> None:
    loop = [
        tool_call_response([ToolCall(id=f"s{i}", name="list_dir", arguments={})]) for i in range(20)
    ]
    agent, main_llm, _ = delegate_setup(tmp_path, loop)  # type: ignore[arg-type]
    agent.run("go")
    report = main_llm.calls[1].messages[-1].tool_results[0].content
    assert "stopped early: max_steps" in report


# --- verify ----------------------------------------------------------------------------------


class Checks:
    """A scripted verification command: returns the given exit codes in order."""

    def __init__(self, exit_codes: list[int]) -> None:
        self.exit_codes = exit_codes
        self.commands: list[str] = []

    def __call__(self, command: str) -> tuple[int, str]:
        self.commands.append(command)
        code = self.exit_codes.pop(0)
        return code, "1 passed" if code == 0 else "FAILED test_add - assert -1 == 5"


def plain_agent(script: list[LLMResponse | str], **guards: int) -> tuple[Agent, FakeLLMClient]:
    llm = FakeLLMClient(script=script)
    return Agent(llm, ToolRegistry(), Guards(**guards), permission=PermissionPolicy()), llm


def test_verified_on_first_check() -> None:
    agent, llm = plain_agent(["fixed"])
    checks = Checks([0])
    verified = run_with_verification(agent, "fix it", command="pytest -q", run_check=checks)
    assert (verified.verified, verified.rounds, len(llm.calls)) == (True, 1, 1)
    assert checks.commands == ["pytest -q"]


def test_failure_output_is_fed_back_until_it_passes() -> None:
    agent, llm = plain_agent(["fixed (not really)", "fixed for real"])
    verified = run_with_verification(agent, "fix it", command="pytest -q", run_check=Checks([1, 0]))

    assert verified.verified and verified.rounds == 2
    feedback = llm.calls[1].messages[-1].content
    assert "pytest -q" in feedback
    assert "FAILED test_add" in feedback
    assert verified.usage == Usage(input_tokens=20, output_tokens=10)


def test_gives_up_after_max_rounds() -> None:
    agent, llm = plain_agent(["try 1", "try 2", "try 3"])
    verified = run_with_verification(
        agent, "fix it", command="pytest -q", run_check=Checks([1, 1, 1]), max_rounds=3
    )
    assert (verified.verified, verified.rounds, len(llm.calls)) == (False, 3, 3)
    assert "FAILED" in verified.check_output


def test_no_check_when_the_agent_did_not_finish() -> None:
    loop = [tool_call_response([ToolCall(id=f"c{i}", name="nope", arguments={})]) for i in range(5)]
    agent, _ = plain_agent(loop, max_steps=2)  # type: ignore[arg-type]
    checks = Checks([0])
    verified = run_with_verification(agent, "fix it", command="pytest -q", run_check=checks)
    assert verified.result.stop_reason == "max_steps"
    assert not verified.verified
    assert checks.commands == []  # respect the user's limits: no extra rounds
