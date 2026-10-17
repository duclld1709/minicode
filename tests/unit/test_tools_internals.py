from pathlib import Path

import pytest

from minicode.tools.base import Tool, ToolError, ToolRegistry, truncate_output
from minicode.tools.fs import ReadFileArgs
from minicode.tools.shell import RunBashArgs, ShellTool, find_bash, scrubbed_env

pytestmark = pytest.mark.m2


def test_short_output_is_untouched() -> None:
    assert truncate_output("a\nb", max_lines=10, max_chars=100) == "a\nb"


def test_very_long_single_line_is_cut_by_chars() -> None:
    result = truncate_output("x" * 1000, max_lines=10, max_chars=100)
    assert "[truncated 900 chars]" in result
    assert len(result) < 200


def test_invalid_tool_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        ToolRegistry().register(Tool("read file", "bad name", ReadFileArgs, str, "read"))


def test_minicode_bash_overrides_discovery() -> None:
    assert find_bash({"MINICODE_BASH": "/opt/bash"}) == "/opt/bash"


def test_scrubbed_env_drops_credentials() -> None:
    env = scrubbed_env(
        {"PATH": "/bin", "OPENAI_API_KEY": "k", "GITHUB_TOKEN": "t", "DB_PASSWORD": "p"}
    )
    assert env == {"PATH": "/bin"}


def test_missing_bash_is_a_tool_error(tmp_path: Path) -> None:
    shell = ShellTool(tmp_path, bash=None, environ={})
    with pytest.raises(ToolError, match="MINICODE_BASH"):
        shell.run_bash(RunBashArgs(command="echo hi"))
