"""JSONL tracing: one file per session in `.minicode/traces/`, one JSON object per line.

Event types:
    session_start  model, provider, cwd, mode
    run_start      task
    llm_call       label, model, latency_ms, usage, cost, stop_reason, text preview, tool calls
    tool_call      name, arguments, latency_ms, is_error, result size and preview
    notice         message (routing, compaction...)
    run_end        stop_reason, steps, usage, cost, wall_ms
    error          message

JSONL because it is append-only (a crash still leaves a readable file), greppable,
and trivially loaded line by line. Every line is passed through `mask_secrets`
before it is written: traces get shared, keys must never be in them.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from minicode.llm.base import LLMClient, TextCallback
from minicode.llm.pricing import Price, estimate_cost
from minicode.llm.types import LLMResponse, Message, ToolCall, ToolResult

TRACES_DIR = Path(".minicode") / "traces"
PREVIEW_CHARS = 300

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI / Anthropic style keys
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),  # GitHub personal tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key ids
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),  # Slack tokens
]
MASK = "***"


def mask_secrets(text: str, known_secrets: Iterable[str] = ()) -> str:
    """Replace known secret values and anything that looks like a key with ***."""
    for secret in known_secrets:
        if len(secret) >= 8:  # never mask tiny strings: that would destroy the trace
            text = text.replace(secret, MASK)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(MASK, text)
    return text


def preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + f"... (+{len(text) - limit} chars)"


def new_trace_path(workspace: Path, clock: Callable[[], datetime] = datetime.now) -> Path:
    stamp = clock().strftime("%Y%m%d-%H%M%S")
    return workspace / TRACES_DIR / f"{stamp}-{uuid.uuid4().hex[:6]}.jsonl"


class Tracer:
    """Appends masked JSON events to one file. Safe to call from several threads."""

    def __init__(
        self,
        path: Path,
        *,
        secrets: Iterable[str] = (),
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.secrets = [s for s in secrets if s]
        self.clock = clock
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **data: Any) -> None:
        record = {"ts": round(self.clock(), 3), "type": kind, **data}
        line = mask_secrets(json.dumps(record, ensure_ascii=False, default=str), self.secrets)
        with self._lock, self.path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")


class TracedLLM:
    """LLMClient wrapper that records every call (latency, tokens, cost) to the tracer."""

    def __init__(
        self,
        llm: LLMClient,
        tracer: Tracer,
        *,
        label: str = "main",
        prices: dict[str, Price] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.llm = llm
        self.model = llm.model
        self.tracer = tracer
        self.label = label
        self.prices = prices or {}
        self.clock = clock

    def complete(
        self,
        messages: list[Message],
        *,
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
        on_text: TextCallback | None = None,
    ) -> LLMResponse:
        started = self.clock()
        response = self.llm.complete(
            messages, system=system, tools=tools, max_tokens=max_tokens, on_text=on_text
        )
        self.tracer.event(
            "llm_call",
            label=self.label,
            model=self.model,
            latency_ms=round((self.clock() - started) * 1000),
            messages=len(messages),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost=estimate_cost(self.model, response.usage, self.prices),
            stop_reason=response.stop_reason,
            text=preview(response.text),
            tool_calls=[{"name": c.name, "arguments": c.arguments} for c in response.tool_calls],
        )
        return response


class TraceListener:
    """AgentListener that records tool calls and notices.

    Latency is measured from `on_tool_call` to `on_tool_result`. For parallel reads
    the results are reported in order, so a fast call that waited for a slower
    one reports the longer time.
    """

    def __init__(self, tracer: Tracer, clock: Callable[[], float] = time.perf_counter) -> None:
        self.tracer = tracer
        self.clock = clock
        self._started: dict[str, float] = {}

    def on_text(self, chunk: str) -> None:
        pass

    def on_tool_call(self, call: ToolCall) -> None:
        self._started[call.id] = self.clock()

    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        started = self._started.pop(call.id, self.clock())
        self.tracer.event(
            "tool_call",
            name=call.name,
            arguments=call.arguments,
            latency_ms=round((self.clock() - started) * 1000),
            is_error=result.is_error,
            result_chars=len(result.content),
            result=preview(result.content),
        )

    def on_notice(self, message: str) -> None:
        self.tracer.event("notice", message=message)


class FanoutListener:
    """Forwards every event to several listeners (e.g. the terminal UI and the tracer)."""

    def __init__(self, *listeners: Any) -> None:
        self.listeners = listeners

    def on_text(self, chunk: str) -> None:
        for listener in self.listeners:
            listener.on_text(chunk)

    def on_tool_call(self, call: ToolCall) -> None:
        for listener in self.listeners:
            listener.on_tool_call(call)

    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        for listener in self.listeners:
            listener.on_tool_result(call, result)

    def on_notice(self, message: str) -> None:
        for listener in self.listeners:
            listener.on_notice(message)

    def end_line(self) -> None:
        for listener in self.listeners:
            end_line = getattr(listener, "end_line", None)
            if end_line is not None:
                end_line()


def load_trace(path: Path) -> list[dict[str, Any]]:
    """Read a trace; a truncated last line (crash mid-write) is skipped."""
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def latest_trace(workspace: Path) -> Path | None:
    traces = sorted((workspace / TRACES_DIR).glob("*.jsonl"))
    return traces[-1] if traces else None
