"""An LLMClient wrapper that adds up the usage of every call made through it.

Helpers like `complete_structured` return only their parsed result, but their
calls still cost money. Wrapping the client is the least invasive way to know
how much a side task (routing, a commit-message chain...) consumed.
"""

from __future__ import annotations

import threading
from typing import Any

from minicode.llm.base import LLMClient, TextCallback
from minicode.llm.types import LLMResponse, Message, Usage


class MeteredLLM:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self.model = llm.model
        self.usage = Usage()
        self.calls = 0
        self._lock = threading.Lock()  # subagents may call from worker threads

    def complete(
        self,
        messages: list[Message],
        *,
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
        on_text: TextCallback | None = None,
    ) -> LLMResponse:
        response = self.llm.complete(
            messages, system=system, tools=tools, max_tokens=max_tokens, on_text=on_text
        )
        with self._lock:
            self.usage = self.usage + response.usage
            self.calls += 1
        return response
