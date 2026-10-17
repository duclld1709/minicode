"""The agent loop: Observe -> Think -> Act, until the model stops asking for tools.

    while True:
        stop if a guard says so                 (steps, tokens, cost, wall time)
        response = llm.complete(history)        (think)
        if no tool calls: done                  (the model answered)
        for each tool call:                     (act)
            run it if permission allows, else return a "denied" result
        append the results to history           (observe)

There is no framework here on purpose: this ~150-line file *is* the agent.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from minicode.agent.context import Compactor
from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.prompts import wrap_tool_output
from minicode.llm.base import LLMClient
from minicode.llm.pricing import Price, estimate_cost
from minicode.llm.types import Message, ToolCall, ToolResult, Usage
from minicode.tools.base import ToolRegistry

INTERRUPTED_RESULT = "Interrupted by the user before this tool call ran."


@dataclass
class AgentResult:
    final_text: str
    steps: int
    usage: Usage
    stop_reason: str
    cost: float | None = None


class AgentListener(Protocol):
    """Receives progress events, e.g. to render them in the terminal."""

    def on_text(self, chunk: str) -> None: ...
    def on_tool_call(self, call: ToolCall) -> None: ...
    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None: ...
    def on_notice(self, message: str) -> None: ...


class NullListener:
    """Ignores all events (tests, library use)."""

    def on_text(self, chunk: str) -> None:
        pass

    def on_tool_call(self, call: ToolCall) -> None:
        pass

    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        pass

    def on_notice(self, message: str) -> None:
        pass


@dataclass
class _RunState:
    """Counters for one `run()` call."""

    started_at: float
    steps: int = 0
    usage: Usage = field(default_factory=Usage)
    last_text: str = ""


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        guards: Guards,
        *,
        permission: PermissionPolicy | None = None,
        system: str = "",
        listener: AgentListener | None = None,
        max_tokens: int = 4096,
        prices: dict[str, Price] | None = None,
        clock: Callable[[], float] = time.monotonic,
        compactor: Compactor | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.guards = guards
        # Safe default: anything risky is refused unless a prompt is wired in.
        self.permission = permission if permission is not None else PermissionPolicy()
        self.system = system
        self.listener: AgentListener = listener if listener is not None else NullListener()
        self.max_tokens = max_tokens
        self.prices = prices or {}
        self.clock = clock
        self.compactor = compactor
        # Kept across run() calls, so a REPL session is one continuous conversation.
        self.history: list[Message] = []

    def run(self, task: str) -> AgentResult:
        """Work on `task` until done or stopped. Never loses history, even on Ctrl+C."""
        self.history.append(Message.user(task))
        state = _RunState(started_at=self.clock())
        try:
            return self._loop(state)
        except KeyboardInterrupt:
            self._close_dangling_tool_calls()
            return self._result(state, "interrupted")
        except Exception:
            # e.g. a provider/network error: keep history valid for the next run, then re-raise.
            self._close_dangling_tool_calls()
            raise

    def _loop(self, state: _RunState) -> AgentResult:
        while True:
            stop_reason = self.guards.check(
                steps=state.steps,
                usage=state.usage,
                cost=self._cost(state.usage),
                elapsed=self.clock() - state.started_at,
            )
            if stop_reason is not None:
                return self._result(state, stop_reason)

            response = self.llm.complete(
                self.history,
                system=self.system,
                tools=self.registry.schemas(),
                max_tokens=self.max_tokens,
                on_text=self.listener.on_text,
            )
            state.steps += 1
            state.usage = state.usage + response.usage
            state.last_text = response.text
            self.history.append(Message.assistant(response))

            if not response.tool_calls:
                truncated = response.stop_reason == "max_tokens"
                return self._result(state, "output_truncated" if truncated else "completed")

            results = self._open_tool_message()
            for call in response.tool_calls:
                results.append(self._execute(call))
            self._maybe_compact(state)

    def _maybe_compact(self, state: _RunState) -> None:
        if self.compactor is None:
            return
        compaction = self.compactor.maybe_compact(self.history, self.system)
        if compaction.changed:
            self.history = compaction.messages
            state.usage = state.usage + compaction.usage  # the summary call costs money too
            self.listener.on_notice(
                f"Context compacted: {compaction.cleared_results} old tool result(s) cleared, "
                f"{compaction.summarized_messages} message(s) summarized."
            )

    def _open_tool_message(self) -> list[ToolResult]:
        """Append an empty tool message and return its list, filled in as tools finish.

        Appending first means that if Ctrl+C lands mid-way, the results gathered so
        far are already in history and only the missing ones need a placeholder.
        """
        message = Message.tool([])
        self.history.append(message)
        return message.tool_results

    def _execute(self, call: ToolCall) -> ToolResult:
        self.listener.on_tool_call(call)
        decision = self.permission.decide(call, self.registry.get(call.name))
        if not decision.allowed:
            denied = ToolResult(
                call_id=call.id,
                content=f"{decision.reason} Do not retry this call; try another approach "
                "or explain to the user what you need.",
                is_error=True,
            )
            self.listener.on_tool_result(call, denied)
            return denied
        result = self.registry.execute(call)
        self.listener.on_tool_result(call, result)
        # What the tool returned is untrusted data (file contents, command output):
        # mark it as such before the model sees it.
        return result.model_copy(update={"content": wrap_tool_output(call.name, result.content)})

    def _close_dangling_tool_calls(self) -> None:
        """Give every tool call in the last assistant turn a result.

        Both providers reject a history where a tool call has no matching result,
        so an interrupted turn would break the *next* request in the session.
        """
        if self.history and self.history[-1].role == "assistant" and self.history[-1].tool_calls:
            self.history.append(Message.tool([]))  # interrupted before any tool started
        if len(self.history) < 2:
            return
        assistant, tool_message = self.history[-2], self.history[-1]
        if assistant.role != "assistant" or tool_message.role != "tool":
            return  # interrupted while the model was thinking: nothing is dangling
        answered = {r.call_id for r in tool_message.tool_results}
        for call in assistant.tool_calls:
            if call.id not in answered:
                tool_message.tool_results.append(
                    ToolResult(call_id=call.id, content=INTERRUPTED_RESULT, is_error=True)
                )

    def _cost(self, usage: Usage) -> float | None:
        return estimate_cost(self.llm.model, usage, self.prices)

    def _result(self, state: _RunState, stop_reason: str) -> AgentResult:
        return AgentResult(
            final_text=state.last_text,
            steps=state.steps,
            usage=state.usage,
            stop_reason=stop_reason,
            cost=self._cost(state.usage),
        )
