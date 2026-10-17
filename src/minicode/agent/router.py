"""Routing: a small model classifies each task before the main agent starts.

Pattern: one cheap call decides *which path* the expensive work takes. Here the
two paths are:

- "question": the user wants information (explain, find, summarize). The agent
  gets read-only tools only, so a question can never modify the project.
- "edit": the user wants changes. The agent gets the full toolbelt.

If routing fails (bad output, provider error) we fall back to "edit": the full
toolbelt is still guarded by permissions, while refusing to work is useless.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from minicode.llm.base import LLMClient
from minicode.llm.metered import MeteredLLM
from minicode.llm.structured import complete_structured
from minicode.llm.types import Usage

ROUTER_PROMPT = """\
Classify this request to a coding agent.
- "question": the user only wants information: explain code, find where something is, review,
  summarize, answer a question. Nothing in the project should change.
- "edit": the user wants something changed or created: fix, implement, refactor, add tests, run
  and repair, update files. When unsure, choose "edit".

Request:
<request>
{task}
</request>"""


class TaskRoute(BaseModel):
    kind: Literal["question", "edit"]
    reason: str = Field(default="", description="One short sentence explaining the choice.")


class Router:
    def __init__(self, llm: LLMClient, max_retries: int = 1) -> None:
        self.llm = llm  # the small model
        self.max_retries = max_retries

    def route(self, task: str) -> tuple[TaskRoute, Usage]:
        """Return the route and the tokens it cost. Never raises."""
        metered = MeteredLLM(self.llm)
        try:
            route = complete_structured(
                metered,
                ROUTER_PROMPT.format(task=task),
                TaskRoute,
                max_retries=self.max_retries,
                max_tokens=300,
            )
        except Exception:
            route = TaskRoute(kind="edit", reason="routing failed; defaulting to the full toolbelt")
        return route, metered.usage
