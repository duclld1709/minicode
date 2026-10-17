"""Contract tests for JSONL tracing and replay (M7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from minicode import cli
from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.loop import Agent
from minicode.llm.fake_client import FakeLLMClient, text_response, tool_call_response
from minicode.llm.pricing import Price
from minicode.llm.types import ToolCall, Usage
from minicode.tools.toolbelt import build_registry
from minicode.tracing import (
    TRACES_DIR,
    FanoutListener,
    TracedLLM,
    TraceListener,
    Tracer,
    load_trace,
    mask_secrets,
)
from minicode.ui import render_trace, trace_totals

pytestmark = pytest.mark.m7

FAKE_KEY = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX1234"


def ticking(step: float = 0.5) -> object:
    """A clock that advances `step` seconds every time it is read."""
    now = [0.0]

    def clock() -> float:
        now[0] += step
        return now[0]

    return clock


# --- masking ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        FAKE_KEY,
        "sk-ant-api03-abcdefghijklmnopqrstuv",
        "ghp_abcdefghijklmnopqrstuvwxyz12",
        "AKIAABCDEFGHIJKLMNOP",
    ],
)
def test_key_like_strings_are_masked(secret: str) -> None:
    assert mask_secrets(f"token={secret} end") == "token=*** end"


def test_known_secrets_are_masked_even_without_a_pattern() -> None:
    assert (
        mask_secrets("pw is hunter2-very-long", known_secrets=["hunter2-very-long"]) == "pw is ***"
    )


def test_short_known_secrets_are_ignored() -> None:
    assert mask_secrets("a b c", known_secrets=["a"]) == "a b c"


# --- the tracer ---------------------------------------------------------------------------


def test_events_are_appended_as_json_lines(tmp_path: Path) -> None:
    tracer = Tracer(tmp_path / "t.jsonl", clock=lambda: 100.0)
    tracer.event("run_start", task="fix it")
    tracer.event("notice", message="hello")
    lines = (tmp_path / "t.jsonl").read_text().splitlines()
    assert [json.loads(line)["type"] for line in lines] == ["run_start", "notice"]
    assert json.loads(lines[0]) == {"ts": 100.0, "type": "run_start", "task": "fix it"}


def test_load_trace_skips_a_truncated_last_line(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_text('{"type": "run_start"}\n{"type": "llm_ca')
    assert load_trace(path) == [{"type": "run_start"}]


def test_traced_llm_records_latency_tokens_and_cost(tmp_path: Path) -> None:
    tracer = Tracer(tmp_path / "t.jsonl")
    inner = FakeLLMClient(
        script=[text_response("hi", Usage(input_tokens=1_000_000, output_tokens=0))]
    )
    llm = TracedLLM(
        inner,
        tracer,
        prices={"fake-model": Price(input_per_mtok=2.0, output_per_mtok=0)},
        clock=ticking(),
    )  # type: ignore[arg-type]

    response = llm.complete([], system="", tools=[], max_tokens=10)

    assert response.text == "hi"
    [event] = load_trace(tracer.path)
    assert event["type"] == "llm_call"
    assert event["latency_ms"] == 500
    assert event["input_tokens"] == 1_000_000
    assert event["cost"] == pytest.approx(2.0)


def test_agent_run_is_fully_traced_and_secrets_never_reach_disk(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / ".env").write_text(f"OPENAI_API_KEY={FAKE_KEY}\n")
    tracer = Tracer(tmp_path / "trace.jsonl")
    read = ToolCall(id="c1", name="read_file", arguments={"path": ".env"})
    llm = TracedLLM(FakeLLMClient(script=[tool_call_response([read]), "done"]), tracer)
    agent = Agent(
        llm,
        build_registry(workspace, environ={}),
        Guards(),
        permission=PermissionPolicy(),
        listener=FanoutListener(TraceListener(tracer)),
    )

    agent.run("show me the env file")

    events = load_trace(tracer.path)
    assert [e["type"] for e in events] == ["llm_call", "tool_call", "llm_call"]
    assert events[1]["name"] == "read_file" and events[1]["is_error"] is False
    raw = tracer.path.read_text()
    assert FAKE_KEY not in raw
    assert "***" in raw


# --- replay ---------------------------------------------------------------------------------


EVENTS = [
    {"ts": 10.0, "type": "run_start", "task": "fix"},
    {
        "ts": 11.0,
        "type": "llm_call",
        "label": "main",
        "latency_ms": 900,
        "input_tokens": 100,
        "output_tokens": 10,
        "cost": 0.01,
        "stop_reason": "tool_use",
        "tool_calls": [{"name": "read_file", "arguments": {}}],
    },
    {
        "ts": 11.1,
        "type": "tool_call",
        "name": "read_file",
        "arguments": {"path": "a.py"},
        "latency_ms": 3,
        "is_error": True,
        "result_chars": 40,
    },
    {
        "ts": 12.0,
        "type": "llm_call",
        "label": "main",
        "latency_ms": 600,
        "input_tokens": 150,
        "output_tokens": 20,
        "cost": 0.02,
        "stop_reason": "end_turn",
        "tool_calls": [],
    },
]


def test_totals_line() -> None:
    assert trace_totals(EVENTS) == (
        "2 LLM calls | in 250 out 30 | $0.0300 | 1 tool calls (1 errors) | LLM time 1.5s"
    )


def test_render_shows_one_line_per_event() -> None:
    console = Console(record=True, width=200)
    render_trace(EVENTS, console)
    lines = console.export_text().splitlines()
    assert len(lines) == len(EVENTS) + 1
    assert "[tool] read_file" in lines[2] and "ERROR" in lines[2]
    assert lines[1].strip().startswith("1.0s")


def test_replay_command_opens_the_latest_trace(tmp_path: Path) -> None:
    traces = tmp_path / TRACES_DIR
    traces.mkdir(parents=True)
    (traces / "20260101-000000-aaaaaa.jsonl").write_text(json.dumps(EVENTS[0]) + "\n")
    (traces / "20260102-000000-bbbbbb.jsonl").write_text("\n".join(json.dumps(e) for e in EVENTS))
    result = CliRunner().invoke(cli.app, ["replay", "--cwd", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "bbbbbb" in result.output
    assert "2 LLM calls" in result.output


def test_replay_without_traces_fails_cleanly(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli.app, ["replay", "--cwd", str(tmp_path)])
    assert result.exit_code == 1
    assert "No trace found" in result.output
