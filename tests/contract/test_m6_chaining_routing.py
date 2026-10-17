"""Contract tests for prompt chaining (commit-msg) and routing (M6)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.loop import Agent
from minicode.agent.router import Router, TaskRoute
from minicode.llm.fake_client import FakeLLMClient, text_response, tool_call_response
from minicode.llm.types import ToolCall, Usage
from minicode.tools.base import Tool, ToolRegistry
from minicode.tools.fs import ReadFileArgs
from minicode.workflows.commit_msg import NoChangesError, read_diff, write_commit_message

pytestmark = pytest.mark.m6

DIFF = "diff --git a/ops.py b/ops.py\n-    return a - b\n+    return a + b\n"


# --- chaining ----------------------------------------------------------------------------


def test_chain_feeds_the_summary_not_the_diff_into_step_two() -> None:
    llm = FakeLLMClient(
        script=[
            text_response(
                "- ops.add now adds instead of subtracting",
                Usage(input_tokens=30, output_tokens=10),
            ),
            text_response(
                "fix(ops): add numbers in add()\n\n- was subtracting",
                Usage(input_tokens=20, output_tokens=12),
            ),
        ]
    )
    result = write_commit_message(llm, DIFF)

    assert result.message.startswith("fix(ops): add numbers in add()")
    assert result.summary == "- ops.add now adds instead of subtracting"
    first, second = llm.calls
    assert DIFF in first.messages[0].content
    assert "ops.add now adds" in second.messages[0].content
    assert "return a - b" not in second.messages[0].content  # step 2 never sees the raw diff
    assert result.usage == Usage(input_tokens=50, output_tokens=22)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_read_diff_prefers_staged_changes(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("one\n")
    (tmp_path / "b.txt").write_text("one\n")
    git("add", ".")
    git("commit", "-q", "-m", "init")

    with pytest.raises(NoChangesError):
        read_diff(tmp_path)
    (tmp_path / "a.txt").write_text("two\n")
    assert "a.txt" in read_diff(tmp_path)  # unstaged only
    (tmp_path / "b.txt").write_text("two\n")
    git("add", "b.txt")
    staged = read_diff(tmp_path)
    assert "b.txt" in staged and "a.txt" not in staged


# --- routing ---------------------------------------------------------------------------------


def registry_with_all_risks() -> ToolRegistry:
    registry = ToolRegistry()
    for name, risk in [("read_file", "read"), ("edit_file", "write"), ("run_bash", "exec")]:
        registry.register(Tool(name, name, ReadFileArgs, str, risk))  # type: ignore[arg-type]
    return registry


def test_router_parses_structured_output() -> None:
    small = FakeLLMClient(
        script=[
            text_response(
                '{"kind": "question", "reason": "asks how"}', Usage(input_tokens=5, output_tokens=5)
            )
        ]
    )
    route, usage = Router(small).route("How does median work?")
    assert route == TaskRoute(kind="question", reason="asks how")
    assert usage == Usage(input_tokens=5, output_tokens=5)
    assert "How does median work?" in small.calls[0].messages[0].content


def test_router_falls_back_to_edit() -> None:
    small = FakeLLMClient(script=["nonsense", "still nonsense"])
    route, _ = Router(small, max_retries=1).route("whatever")
    assert route.kind == "edit"


@pytest.mark.parametrize(
    ("kind", "expected_tools"),
    [("question", {"read_file"}), ("edit", {"read_file", "edit_file", "run_bash"})],
)
def test_route_decides_the_toolbelt(kind: str, expected_tools: set[str]) -> None:
    small = FakeLLMClient(script=[f'{{"kind": "{kind}", "reason": "r"}}'])
    main = FakeLLMClient(script=["answer"])
    agent = Agent(
        main,
        registry_with_all_risks(),
        Guards(),
        permission=PermissionPolicy(),
        router=Router(small),
    )

    result = agent.run("task")

    assert {t["name"] for t in main.calls[0].tools} == expected_tools
    assert result.usage.input_tokens == 20  # 10 for routing + 10 for the main call


def test_question_route_cannot_reach_write_tools() -> None:
    small = FakeLLMClient(script=['{"kind": "question", "reason": "r"}'])
    sneaky = ToolCall(id="c1", name="edit_file", arguments={"path": "x"})
    main = FakeLLMClient(script=[tool_call_response([sneaky]), "ok"])
    agent = Agent(
        main,
        registry_with_all_risks(),
        Guards(),
        permission=PermissionPolicy(mode="auto"),
        router=Router(small),
    )
    agent.run("explain x")
    result = main.calls[1].messages[-1].tool_results[0]
    assert result.is_error
    assert "Unknown tool" in result.content
