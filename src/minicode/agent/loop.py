"""The agent loop: Observe -> Think -> Act, until the model stops asking for tools.

    route the task (optional)                   (question -> read-only tools)
    while True:
        stop if a guard says so                 (steps, tokens, cost, wall time)
        response = llm.complete(history)        (think)
        if no tool calls: done                  (the model answered)
        for each tool call:                     (act; consecutive reads run in parallel)
            run it if permission allows, else return a "denied" result
        append the results to history           (observe)
        compact the history if it got too big

There is no framework here on purpose: this file *is* the agent.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from minicode.agent.context import Compactor
from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.prompts import wrap_tool_output
from minicode.agent.router import Router
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
        router: Router | None = None,
        max_parallel_tools: int = 8,
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
        self.router = router
        self.max_parallel_tools = max_parallel_tools
        # Kept across run() calls, so a REPL session is one continuous conversation.
        self.history: list[Message] = []
        self._tools = registry  # the toolbelt for the current run (see _choose_tools)
        self._state: _RunState | None = None
        self._usage_lock = threading.Lock()

    def run(self, task: str) -> AgentResult:
        """Work on `task` until done or stopped. Never loses history, even on Ctrl+C."""
        self.history.append(Message.user(task))
        state = _RunState(started_at=self.clock())
        self._state = state
        try:
            self._tools = self._choose_tools(task)
            return self._loop(state)
        except KeyboardInterrupt:
            self._close_dangling_tool_calls()
            return self._result(state, "interrupted")
        except Exception:
            # e.g. a provider/network error: keep history valid for the next run, then re-raise.
            self._close_dangling_tool_calls()
            raise
        finally:
            self._state = None

    def add_usage(self, usage: Usage) -> None:
        """Count tokens spent on our behalf (e.g. by a subagent) toward this run's budget."""
        with self._usage_lock:  # subagents may report from worker threads
            if self._state is not None:
                self._state.usage = self._state.usage + usage

    def _choose_tools(self, task: str) -> ToolRegistry:
        """Routing: questions get read-only tools, edits get everything."""
        if self.router is None:
            return self.registry
        route, usage = self.router.route(task)
        self.add_usage(usage)
        self.listener.on_notice(f"Route: {route.kind} ({route.reason})")
        if route.kind == "question":
            return self.registry.subset(lambda tool: tool.risk == "read")
        return self.registry

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
                tools=self._tools.schemas(),
                max_tokens=self.max_tokens,
                on_text=self.listener.on_text,
            )
            state.steps += 1
            self.add_usage(response.usage)
            state.last_text = response.text
            self.history.append(Message.assistant(response))

            if not response.tool_calls:
                truncated = response.stop_reason == "max_tokens"
                return self._result(state, "output_truncated" if truncated else "completed")

            self._execute_all(response.tool_calls, self._open_tool_message())
            self._maybe_compact()

    # --- acting ------------------------------------------------------------------------

    def _open_tool_message(self) -> list[ToolResult]:
        """Append an empty tool message and return its list, filled in as tools finish.

        Appending first means that if Ctrl+C lands mid-way, the results gathered so
        far are already in history and only the missing ones need a placeholder.
        """
        message = Message.tool([])
        self.history.append(message)
        return message.tool_results

    def _execute_all(self, calls: list[ToolCall], results: list[ToolResult]) -> None:
        """Run calls in order; each run of consecutive `read` calls executes in parallel.

        Reads have no side effects and never need a permission prompt, so running
        them together is safe. Anything else runs alone, in order, because it may
        prompt the user or depend on an earlier call (edit, then run tests).
        """
        batch: list[ToolCall] = []
        for call in calls:
            tool = self._tools.get(call.name)
            if tool is not None and tool.risk == "read":
                batch.append(call)
                continue
            self._execute_parallel(batch, results)
            batch = []
            results.append(self._execute(call))
        self._execute_parallel(batch, results)

    def _execute_parallel(self, calls: list[ToolCall], results: list[ToolResult]) -> None:
        if len(calls) <= 1:
            results.extend(self._execute(call) for call in calls)
            return
        for call in calls:
            self.listener.on_tool_call(call)
        workers = min(self.max_parallel_tools, len(calls))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._tools.execute, call) for call in calls]
            # Collect in the original order, one by one: if Ctrl+C arrives (or a worker
            # re-raises it), the results collected so far are already in history.
            for call, future in zip(calls, futures, strict=True):
                result = future.result()
                self.listener.on_tool_result(call, result)
                results.append(self._as_data(call, result))

    def _execute(self, call: ToolCall) -> ToolResult:
        self.listener.on_tool_call(call)
        decision = self.permission.decide(call, self._tools.get(call.name))
        if not decision.allowed:
            denied = ToolResult(
                call_id=call.id,
                content=f"{decision.reason} Do not retry this call; try another approach "
                "or explain to the user what you need.",
                is_error=True,
            )
            self.listener.on_tool_result(call, denied)
            return denied
        result = self._tools.execute(call)
        self.listener.on_tool_result(call, result)
        return self._as_data(call, result)

    @staticmethod
    def _as_data(call: ToolCall, result: ToolResult) -> ToolResult:
        # What the tool returned is untrusted data (file contents, command output):
        # mark it as such before the model sees it.
        return result.model_copy(update={"content": wrap_tool_output(call.name, result.content)})

    # --- housekeeping ------------------------------------------------------------------

    def _maybe_compact(self) -> None:
        if self.compactor is None:
            return
        compaction = self.compactor.maybe_compact(self.history, self.system)
        if compaction.changed:
            self.history = compaction.messages
            self.add_usage(compaction.usage)  # the summary call costs money too
            self.listener.on_notice(
                f"Context compacted: {compaction.cleared_results} old tool result(s) cleared, "
                f"{compaction.summarized_messages} message(s) summarized."
            )

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
        # Simplification: every token is priced at the main model's rate, including
        # small-model side calls (routing, summaries), so this slightly overestimates.
        return estimate_cost(self.llm.model, usage, self.prices)

    def _result(self, state: _RunState, stop_reason: str) -> AgentResult:
        return AgentResult(
            final_text=state.last_text,
            steps=state.steps,
            usage=state.usage,
            stop_reason=stop_reason,
            cost=self._cost(state.usage),
        )
