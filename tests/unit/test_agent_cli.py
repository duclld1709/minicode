"""Agent-facing CLI, UI rendering and the system prompt (M3)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from typer.testing import CliRunner

from minicode import cli
from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.loop import Agent
from minicode.llm.fake_client import FakeLLMClient, tool_call_response
from minicode.llm.types import LLMResponse, ToolCall, ToolResult
from minicode.tools.base import Tool, ToolRegistry
from minicode.tools.fs import ReadFileArgs
from minicode.ui import RichListener, make_permission_prompt, preview, short_args

pytestmark = pytest.mark.m3


def lines(answers: list[str]) -> Callable[[], str]:
    remaining = iter(answers)

    def read() -> str:
        try:
            return next(remaining)
        except StopIteration:
            raise EOFError from None

    return read


def record_console() -> Console:
    return Console(record=True, width=200, force_terminal=False)


# --- ui.py ---------------------------------------------------------------------------


def test_short_args_truncates() -> None:
    assert short_args({"path": "a.py"}) == 'path="a.py"'
    assert short_args({"text": "x" * 500}, limit=20).endswith("...")


def test_preview_counts_hidden_lines() -> None:
    assert preview("1\n2\n3\n4\n5\n6", max_lines=2) == "1\n2\n... (4 more lines)"


def test_tool_output_is_never_interpreted_as_markup() -> None:
    console = record_console()
    listener = RichListener(console)
    call = ToolCall(id="c", name="read_file", arguments={"path": "[bold]x"})
    listener.on_tool_call(call)
    listener.on_tool_result(call, ToolResult(call_id="c", content="[red]FAKE PROMPT[/red]"))
    output = console.export_text()
    assert "[red]FAKE PROMPT[/red]" in output
    assert "[bold]x" in output


@pytest.mark.parametrize(
    ("typed", "expected"), [(["y"], "yes"), (["no"], "no"), (["maybe", "a"], "always"), ([], "no")]
)
def test_permission_prompt_answers(typed: list[str], expected: str) -> None:
    prompt = make_permission_prompt(record_console(), lines(typed))
    tool = Tool("run_bash", "", ReadFileArgs, str, "exec")
    assert prompt(ToolCall(id="c", name="run_bash", arguments={"command": "ls"}), tool) == expected


# --- cli.py ---------------------------------------------------------------------------------


@pytest.fixture
def fake_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)  # keep the repo's real .env out of it
    monkeypatch.setenv("MINICODE_PROVIDER", "openai")
    monkeypatch.setenv("MINICODE_MODEL", "fake-model")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    (tmp_path / "README.md").write_text("hello\n")
    return tmp_path


def patch_llm(monkeypatch: pytest.MonkeyPatch, script: list[LLMResponse | str]) -> None:
    def fake_create_client(settings: Any, small: bool = False) -> FakeLLMClient:
        return FakeLLMClient(script=list(script))

    monkeypatch.setattr(cli, "create_client", fake_create_client)


def test_run_command_completes(fake_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    read = ToolCall(id="c1", name="read_file", arguments={"path": "README.md"})
    patch_llm(monkeypatch, [tool_call_response([read]), "Read it."])

    result = CliRunner().invoke(cli.app, ["run", "read the readme", "--mode", "auto"])

    assert result.exit_code == 0, result.output
    assert "> read_file" in result.output
    assert "Read it." in result.output
    assert "completed | 2 steps" in result.output


def test_run_command_exit_code_when_stopped(
    fake_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    looping = [
        tool_call_response([ToolCall(id=f"c{i}", name="list_dir", arguments={})]) for i in range(5)
    ]
    patch_llm(monkeypatch, looping)
    result = CliRunner().invoke(cli.app, ["run", "loop", "--mode", "auto", "--max-steps", "2"])
    assert result.exit_code == 1
    assert "max_steps" in result.output


def test_agent_repl_runs_tasks_until_exit() -> None:
    console = record_console()
    llm = FakeLLMClient(script=["one", "two"])
    agent = Agent(
        llm, ToolRegistry(), Guards(), permission=PermissionPolicy(), listener=RichListener(console)
    )
    cli.agent_repl(agent, console, lines(["first", "", "second", "/exit", "never"]))
    assert len(llm.calls) == 2
    assert console.export_text().count("completed") == 2


def test_provider_error_is_reported_not_raised() -> None:
    console = record_console()
    agent = Agent(FakeLLMClient(script=[]), ToolRegistry(), Guards())
    assert cli.run_task(agent, "go", console) is None
    assert "Error: ScriptExhaustedError" in console.export_text()
