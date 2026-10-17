"""Contract tests for todo_write / todo_read (M6)."""

import pytest

from minicode.llm.types import ToolCall, ToolResult
from minicode.tools.base import ToolRegistry
from minicode.tools.todo import TodoList

pytestmark = pytest.mark.m6


def registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in TodoList().tools():
        registry.register(tool)
    return registry


def call(registry: ToolRegistry, name: str, **arguments: object) -> ToolResult:
    return registry.execute(ToolCall(id="c", name=name, arguments=arguments))


def test_write_then_read_the_plan() -> None:
    reg = registry()
    todos = [
        {"content": "Run the tests", "status": "completed"},
        {"content": "Fix add()", "status": "in_progress"},
        {"content": "Re-run the tests"},
    ]
    written = call(reg, "todo_write", todos=todos)
    assert not written.is_error
    assert (
        call(reg, "todo_read").content
        == written.content
        == ("[x] Run the tests\n[>] Fix add()\n[ ] Re-run the tests\n(1/3 completed)")
    )


def test_write_replaces_the_whole_list() -> None:
    reg = registry()
    call(reg, "todo_write", todos=[{"content": "old"}])
    call(reg, "todo_write", todos=[{"content": "new"}])
    assert "old" not in call(reg, "todo_read").content


def test_only_one_item_in_progress() -> None:
    result = call(
        registry(),
        "todo_write",
        todos=[
            {"content": "a", "status": "in_progress"},
            {"content": "b", "status": "in_progress"},
        ],
    )
    assert result.is_error
    assert "one item" in result.content


def test_invalid_items_are_rejected_by_the_schema() -> None:
    reg = registry()
    assert call(reg, "todo_write", todos=[{"content": ""}]).is_error
    assert call(reg, "todo_write", todos=[{"content": "x", "status": "done"}]).is_error


def test_empty_plan() -> None:
    assert call(registry(), "todo_read").content == "(no plan yet)"


def test_todo_tools_need_no_permission() -> None:
    assert all(tool.risk == "read" for tool in TodoList().tools())
