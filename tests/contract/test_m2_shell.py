"""Contract tests for run_bash (M2). Skipped when no bash is available."""

import os
from pathlib import Path

import pytest

from minicode.llm.types import ToolCall, ToolResult
from minicode.tools.base import ToolRegistry
from minicode.tools.shell import find_bash
from minicode.tools.toolbelt import build_registry

pytestmark = [
    pytest.mark.m2,
    pytest.mark.skipif(find_bash(os.environ) is None, reason="bash not available"),
]


@pytest.fixture
def registry(tmp_path: Path) -> ToolRegistry:
    env = {**os.environ, "OPENAI_API_KEY": "sk-should-not-leak"}
    return build_registry(tmp_path, environ=env)


def bash(registry: ToolRegistry, command: str, **extra: object) -> ToolResult:
    return registry.execute(
        ToolCall(id="c1", name="run_bash", arguments={"command": command, **extra})
    )


def test_returns_output_and_exit_code(registry: ToolRegistry) -> None:
    result = bash(registry, "echo hello")
    assert not result.is_error
    assert result.content == "hello\n[exit code: 0]"


def test_failing_command_is_not_a_tool_error(registry: ToolRegistry) -> None:
    result = bash(registry, "echo oops >&2; exit 3")
    assert not result.is_error  # the agent needs to *see* failures, e.g. failing tests
    assert "oops" in result.content
    assert "[exit code: 3]" in result.content


def test_runs_in_the_workspace(registry: ToolRegistry, tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x")
    assert "marker.txt" in bash(registry, "ls").content


def test_timeout_kills_the_command(registry: ToolRegistry) -> None:
    result = bash(registry, "sleep 10", timeout_seconds=1)
    assert result.is_error
    assert "timed out" in result.content


def test_api_keys_are_not_passed_to_commands(registry: ToolRegistry) -> None:
    result = bash(registry, 'echo "key=${OPENAI_API_KEY:-unset}"')
    assert "key=unset" in result.content
    assert "sk-should-not-leak" not in result.content
