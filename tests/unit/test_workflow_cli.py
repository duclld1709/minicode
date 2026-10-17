"""CLI entry points for M6 workflows: `run --verify` and `commit-msg`."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from typer.testing import CliRunner

from minicode import cli
from minicode.llm.fake_client import FakeLLMClient, tool_call_response
from minicode.llm.types import LLMResponse, ToolCall, ToolResult
from minicode.tools.shell import find_bash
from minicode.ui import RichListener

pytestmark = pytest.mark.m6


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for var, value in {
        "MINICODE_PROVIDER": "openai",
        "MINICODE_MODEL": "m",
        "OPENAI_API_KEY": "k",
    }.items():
        monkeypatch.setenv(var, value)
    return tmp_path


def patch_llm(monkeypatch: pytest.MonkeyPatch, script: list[LLMResponse | str]) -> FakeLLMClient:
    llm = FakeLLMClient(script=script)

    def fake_create_client(settings: Any, small: bool = False) -> FakeLLMClient:
        return llm

    monkeypatch.setattr(cli, "create_client", fake_create_client)
    return llm


@pytest.mark.skipif(find_bash(os.environ) is None, reason="bash not available")
def test_run_with_verify_feeds_back_until_the_check_passes(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write = ToolCall(id="w", name="write_file", arguments={"path": "done.txt", "content": "ok"})
    llm = patch_llm(
        monkeypatch, ["I am done (but did nothing).", tool_call_response([write]), "Now done."]
    )

    result = CliRunner().invoke(
        cli.app,
        ["run", "create done.txt", "--mode", "auto", "--no-route", "--verify", "test -f done.txt"],
    )

    assert result.exit_code == 0, result.output
    assert "[verify failed, exit 1]" in result.output
    assert "[verify passed]" in result.output
    assert "verified after 2 check(s)" in result.output
    assert "test -f done.txt" in llm.calls[1].messages[-1].content  # the feedback turn


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_commit_msg_prints_the_chained_message(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    (workspace / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=workspace, check=True)
    patch_llm(monkeypatch, ["- adds a.py", "feat: add a.py"])

    result = CliRunner().invoke(cli.app, ["commit-msg"])

    assert result.exit_code == 0, result.output
    assert "feat: add a.py" in result.output
    assert "2 calls" in result.output


def test_parallel_results_are_labelled_with_their_tool() -> None:
    console = Console(record=True, width=120)
    listener = RichListener(console)
    first, second = (
        ToolCall(id="1", name="read_file", arguments={}),
        ToolCall(id="2", name="grep", arguments={}),
    )
    listener.on_tool_call(first)
    listener.on_tool_call(second)
    listener.on_tool_result(first, ToolResult(call_id="1", content="A"))
    listener.on_tool_result(second, ToolResult(call_id="2", content="B"))
    lines = console.export_text().splitlines()
    assert lines[2:] == ["  < read_file", "  A", "  < grep", "  B"]


def test_commit_msg_outside_a_repo_fails_cleanly(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_llm(monkeypatch, [])
    result = CliRunner().invoke(cli.app, ["commit-msg"])
    assert result.exit_code == 1
    assert "Error" in result.output
