from collections.abc import Callable
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from minicode.chat import ChatSession
from minicode.cli import app, chat_loop, format_usage, short_error
from minicode.llm.fake_client import FakeLLMClient
from minicode.llm.types import Usage

pytestmark = pytest.mark.m0


def scripted_input(lines: list[str]) -> Callable[[], str]:
    """Simulate a user typing `lines`, then pressing Ctrl+D."""
    remaining = iter(lines)

    def read_line() -> str:
        try:
            return next(remaining)
        except StopIteration:
            raise EOFError from None

    return read_line


def record_console() -> Console:
    return Console(record=True, width=120, force_terminal=False)


def test_chat_loop_runs_turns_until_exit() -> None:
    console = record_console()
    llm = FakeLLMClient(script=["Hello there", "Still here"])
    chat_loop(ChatSession(llm), console, scripted_input(["hi", "", "again", "/exit", "ignored"]))

    output = console.export_text()
    assert "Hello there" in output
    assert "Still here" in output
    assert "in 10 | out 5" in output
    assert len(llm.calls) == 2  # blank line skipped, nothing read after /exit


def test_chat_loop_survives_errors() -> None:
    console = record_console()
    chat_loop(ChatSession(FakeLLMClient(script=[])), console, scripted_input(["hi"]))
    assert "Error:" in console.export_text()


def test_format_usage_handles_unknown_cost() -> None:
    line = format_usage(Usage(input_tokens=3, output_tokens=4), None, 0.5)
    assert line == "in 3 | out 4 | cost n/a | session $0.5000"


def test_short_error_truncates() -> None:
    assert short_error(ValueError("x" * 1000)).endswith("...")


def test_chat_command_reports_missing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("MINICODE_PROVIDER", "MINICODE_MODEL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # so the repo's real .env is not picked up

    result = CliRunner().invoke(app, ["chat", "--cwd", str(tmp_path)])

    assert result.exit_code == 2
    assert "MINICODE_PROVIDER" in result.output
