"""Contract tests for the filesystem tools (M2), driven through the registry.

Your toolbelt must be built with `build_registry(root, environ=...)` and expose
read_file, list_dir, glob, grep, write_file, edit_file and run_bash.
"""

import os
from pathlib import Path

import pytest

from minicode.llm.types import ToolCall, ToolResult
from minicode.tools.base import ToolRegistry
from minicode.tools.toolbelt import build_registry

pytestmark = pytest.mark.m2


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (root / "src" / "util.py").write_text("def double(x):\n    return add(x, x)\n")
    (root / "README.md").write_text("# demo\n")
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".venv" / "lib" / "junk.py").write_text("def add(): pass\n")
    (tmp_path / "secret.txt").write_text("top secret")
    return root


@pytest.fixture
def registry(workspace: Path) -> ToolRegistry:
    return build_registry(workspace, environ=dict(os.environ))


def run(registry: ToolRegistry, name: str, **arguments: object) -> ToolResult:
    return registry.execute(ToolCall(id="c1", name=name, arguments=arguments))


def test_toolbelt_has_the_expected_tools(registry: ToolRegistry) -> None:
    names = {s["name"] for s in registry.schemas()}
    expected = {"read_file", "list_dir", "glob", "grep", "write_file", "edit_file", "run_bash"}
    assert names == expected


def test_tools_have_risk_levels(registry: ToolRegistry) -> None:
    risks = {name: registry.get(name).risk for name in registry.names}  # type: ignore[union-attr]
    assert risks["read_file"] == "read"
    assert risks["edit_file"] == "write"
    assert risks["run_bash"] == "exec"


# --- read_file -----------------------------------------------------------------


def test_read_file_numbers_lines(registry: ToolRegistry) -> None:
    result = run(registry, "read_file", path="src/calc.py")
    assert not result.is_error
    assert result.content.splitlines()[1].split("\t") == ["     2", "    return a - b"]


def test_read_file_offset_and_limit(registry: ToolRegistry, workspace: Path) -> None:
    (workspace / "long.txt").write_text("".join(f"line {i}\n" for i in range(1, 51)))
    result = run(registry, "read_file", path="long.txt", offset=10, limit=5)
    assert "line 10" in result.content and "line 14" in result.content
    assert "line 15" not in result.content
    assert "10-14 of 50" in result.content


def test_read_missing_file_is_an_error(registry: ToolRegistry) -> None:
    result = run(registry, "read_file", path="nope.py")
    assert result.is_error
    assert "not found" in result.content.lower()


def test_read_binary_file_is_an_error(registry: ToolRegistry, workspace: Path) -> None:
    (workspace / "image.bin").write_bytes(b"\x89PNG\0\0\0")
    assert run(registry, "read_file", path="image.bin").is_error


# --- list_dir / glob / grep ------------------------------------------------------


def test_list_dir_marks_directories(registry: ToolRegistry) -> None:
    lines = run(registry, "list_dir", path=".").content.splitlines()
    assert "src/" in lines
    assert "README.md" in lines


def test_glob_finds_files_and_skips_virtualenvs(registry: ToolRegistry) -> None:
    result = run(registry, "glob", pattern="**/*.py")
    assert result.content.splitlines() == ["src/calc.py", "src/util.py"]


def test_grep_reports_path_and_line(registry: ToolRegistry) -> None:
    result = run(registry, "grep", pattern=r"add\(", include="*.py")
    assert result.content.splitlines() == [
        "src/calc.py:1: def add(a, b):",
        "src/util.py:2:     return add(x, x)",
    ]


def test_grep_invalid_regex_is_an_error(registry: ToolRegistry) -> None:
    assert run(registry, "grep", pattern="(unclosed").is_error


# --- write_file / edit_file ------------------------------------------------------


def test_write_file_creates_parent_dirs(registry: ToolRegistry, workspace: Path) -> None:
    result = run(registry, "write_file", path="new/dir/x.txt", content="hello\n")
    assert not result.is_error
    assert (workspace / "new" / "dir" / "x.txt").read_text() == "hello\n"


def test_edit_file_replaces_unique_string(registry: ToolRegistry, workspace: Path) -> None:
    result = run(registry, "edit_file", path="src/calc.py", old_string="a - b", new_string="a + b")
    assert not result.is_error
    assert (workspace / "src" / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"


def test_edit_file_missing_string_gives_guidance(registry: ToolRegistry) -> None:
    result = run(registry, "edit_file", path="src/calc.py", old_string="a * b", new_string="x")
    assert result.is_error
    assert "not found" in result.content


def test_edit_file_ambiguous_string_gives_guidance(registry: ToolRegistry, workspace: Path) -> None:
    (workspace / "dup.py").write_text("x = 1\nx = 1\n")
    result = run(registry, "edit_file", path="dup.py", old_string="x = 1", new_string="x = 2")
    assert result.is_error
    assert "2 times" in result.content
    assert (workspace / "dup.py").read_text() == "x = 1\nx = 1\n"  # untouched


def test_edit_file_preserves_crlf(registry: ToolRegistry, workspace: Path) -> None:
    (workspace / "win.txt").write_bytes(b"one\r\ntwo\r\n")
    result = run(registry, "edit_file", path="win.txt", old_string="one\ntwo", new_string="one\n2")
    assert not result.is_error
    assert (workspace / "win.txt").read_bytes() == b"one\r\n2\r\n"


# --- workspace sandbox -------------------------------------------------------------


@pytest.mark.parametrize("tool", ["read_file", "write_file"])
def test_parent_traversal_is_blocked(registry: ToolRegistry, tool: str) -> None:
    result = run(registry, tool, path="../secret.txt", content="x")
    assert result.is_error
    assert "outside the workspace" in result.content


def test_absolute_path_outside_is_blocked(registry: ToolRegistry, workspace: Path) -> None:
    outside = str(workspace.parent / "secret.txt")
    assert run(registry, "read_file", path=outside).is_error


def test_absolute_path_inside_is_allowed(registry: ToolRegistry, workspace: Path) -> None:
    inside = str(workspace / "README.md")
    assert not run(registry, "read_file", path=inside).is_error


def test_symlink_escaping_the_workspace_is_blocked(registry: ToolRegistry, workspace: Path) -> None:
    link = workspace / "sneaky.txt"
    try:
        link.symlink_to(workspace.parent / "secret.txt")
    except OSError:
        pytest.skip("creating symlinks is not permitted on this machine")
    result = run(registry, "read_file", path="sneaky.txt")
    assert result.is_error
    assert "top secret" not in result.content


def test_glob_cannot_escape_with_dotdot(registry: ToolRegistry) -> None:
    result = run(registry, "glob", pattern="../*.txt")
    assert "secret.txt" not in result.content
