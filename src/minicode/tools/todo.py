"""todo_write / todo_read: a plan the agent keeps for itself during multi-step tasks.

Writing the plan down helps the model stay on track over many steps (and helps
the user see where it is). `todo_write` replaces the whole list each time: the
model always sends the full, current plan, so there is no partial-update logic
to get wrong.

The list lives in memory for the session only; it touches no files, so both
tools are "read" risk (no permission prompt).
"""

from __future__ import annotations

import threading
from typing import Literal

from pydantic import BaseModel, Field

from minicode.tools.base import Tool, ToolError

TodoStatus = Literal["pending", "in_progress", "completed"]
MARKS: dict[str, str] = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}


class TodoItem(BaseModel):
    content: str = Field(min_length=1, description="What to do, as a short imperative sentence.")
    status: TodoStatus = "pending"


class TodoWriteArgs(BaseModel):
    todos: list[TodoItem] = Field(description="The complete, updated plan (replaces the old one).")


class TodoReadArgs(BaseModel):
    pass


TODO_WRITE_DOC = (
    "Create or update your plan for a multi-step task. Send the FULL list every time. Mark "
    "exactly one item 'in_progress' while working on it and mark items 'completed' as soon as "
    "they are done."
)
TODO_READ_DOC = "Show your current plan (the list written with todo_write)."


class TodoList:
    def __init__(self) -> None:
        self.items: list[TodoItem] = []
        self._lock = threading.Lock()  # read tools may run in parallel threads

    def tools(self) -> list[Tool]:
        return [
            Tool("todo_write", TODO_WRITE_DOC, TodoWriteArgs, self.write, "read"),
            Tool("todo_read", TODO_READ_DOC, TodoReadArgs, self.read, "read"),
        ]

    def write(self, args: TodoWriteArgs) -> str:
        in_progress = [item for item in args.todos if item.status == "in_progress"]
        if len(in_progress) > 1:
            raise ToolError(
                f"{len(in_progress)} items are 'in_progress'. Work on one thing at a time: mark "
                "exactly one item 'in_progress'."
            )
        with self._lock:
            self.items = list(args.todos)
        return self.render()

    def read(self, args: TodoReadArgs) -> str:
        return self.render()

    def render(self) -> str:
        with self._lock:
            items = list(self.items)
        if not items:
            return "(no plan yet)"
        done = sum(item.status == "completed" for item in items)
        lines = [f"{MARKS[item.status]} {item.content}" for item in items]
        return "\n".join([*lines, f"({done}/{len(items)} completed)"])
