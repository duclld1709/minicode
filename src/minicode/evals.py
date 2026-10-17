"""Evaluation harness: run the agent on fixed tasks and check the outcome objectively.

Layout of one task (`evals/tasks/<task_id>/`):

    task.yaml   prompt, max_steps, category
    repo/       fixture project, copied to a temp dir for every run
    check.py    def check(ctx: EvalContext) -> tuple[bool, str]

A unit test checks code; an eval checks *behaviour of the whole system* (model +
prompt + tools + guards) on realistic tasks, and is scored by pass rate because
the model is not deterministic. `check.py` must judge the result, not the path:
run the tests, inspect files, search the answer for facts, look at which tool
calls were attempted (for injection traps).

`evals/run_evals.py` is the command-line front end; the logic lives here so it is
typed, tested and reusable.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.table import Table

from minicode.agent.loop import Agent
from minicode.llm.types import ToolCall
from minicode.tracing import Tracer

# --- Tasks -----------------------------------------------------------------------------


@dataclass
class EvalTask:
    id: str
    dir: Path
    prompt: str
    max_steps: int = 20
    category: str = ""

    @property
    def repo(self) -> Path:
        return self.dir / "repo"


def load_tasks(tasks_dir: Path, only: list[str] | None = None) -> list[EvalTask]:
    tasks = []
    for task_file in sorted(tasks_dir.glob("*/task.yaml")):
        task_id = task_file.parent.name
        if only and task_id not in only:
            continue
        data = yaml.safe_load(task_file.read_text(encoding="utf-8")) or {}
        tasks.append(
            EvalTask(
                id=task_id,
                dir=task_file.parent,
                prompt=str(data["prompt"]).strip(),
                max_steps=int(data.get("max_steps", 20)),
                category=str(data.get("category", "")),
            )
        )
    return tasks


# --- What check.py receives, and helpers for writing checks ----------------------------------


@dataclass
class EvalContext:
    workspace: Path  # the agent's copy of the repo, after the run
    original: Path  # the untouched fixture repo
    final_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


CheckResult = tuple[bool, str]
CheckFn = Callable[[EvalContext], CheckResult]


def run_pytest(workspace: Path, timeout: float = 120.0) -> CheckResult:
    """Run the fixture's test suite with the current interpreter."""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=workspace,
        # No .pyc files: a check must leave the directory as it found it.
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    output = completed.stdout.decode("utf-8", errors="replace").strip()
    last_line = output.splitlines()[-1] if output else "(no output)"
    return completed.returncode == 0, last_line


def unchanged(ctx: EvalContext, relative_path: str) -> bool:
    """True if the file still exists and is byte-identical to the fixture."""
    current = ctx.workspace / relative_path
    return current.is_file() and current.read_bytes() == (ctx.original / relative_path).read_bytes()


def original_tests_pass(ctx: EvalContext, tests_dir: str = "tests") -> CheckResult:
    """Anti-cheating check for bug fixes: the *original* tests must pass on the agent's code.

    Comparing test files byte for byte is too strict: a good agent may *add* tests.
    Instead: every original test function must still exist, and the untouched
    original tests, run against the agent's code, must pass. Deleting, weakening
    or rewriting a test therefore fails, while adding tests is fine.
    """
    for original in sorted((ctx.original / tests_dir).glob("test_*.py")):
        current = ctx.workspace / tests_dir / original.name
        if not current.is_file():
            return False, f"{tests_dir}/{original.name} was deleted"
        missing = set(_test_names(original)) - set(_test_names(current))
        if missing:
            return False, f"test(s) removed from {original.name}: {', '.join(sorted(missing))}"
    with tempfile.TemporaryDirectory(prefix="minicode-check-") as scratch:
        copy = Path(scratch) / "repo"
        shutil.copytree(ctx.workspace, copy, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ctx.original / tests_dir, copy / tests_dir, dirs_exist_ok=True)
        return run_pytest(copy)


def _test_names(path: Path) -> list[str]:
    return re.findall(r"^def (test_\w+)", path.read_text(encoding="utf-8"), flags=re.MULTILINE)


def tool_calls_text(ctx: EvalContext) -> str:
    """All attempted tool calls as one string, to search for things the agent tried to do."""
    return json.dumps([{"name": c.name, "arguments": c.arguments} for c in ctx.tool_calls])


def contains_all(text: str, words: list[str]) -> bool:
    return all(word.lower() in text.lower() for word in words)


def contains_any(text: str, words: list[str]) -> bool:
    return any(word.lower() in text.lower() for word in words)


def load_check(task: EvalTask) -> CheckFn:
    spec = importlib.util.spec_from_file_location(f"eval_check_{task.id}", task.dir / "check.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load check.py for task {task.id}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check: CheckFn = module.check
    return check


# --- Running -----------------------------------------------------------------------------------

AgentFactory = Callable[[Path, EvalTask, Tracer], Agent]
"""Builds a fresh agent for one task: (workspace, task, tracer) -> Agent."""


@dataclass
class TaskOutcome:
    task_id: str
    category: str
    passed: bool
    reason: str
    stop_reason: str = ""
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None
    seconds: float = 0.0
    trace: str = ""


def run_task(
    task: EvalTask,
    make_agent: AgentFactory,
    scratch: Path,
    clock: Callable[[], float] = time.perf_counter,
) -> TaskOutcome:
    """Copy the fixture, run the agent, judge the result. Never raises."""
    run_dir = scratch / task.id
    workspace = run_dir / "workspace"  # the run dir is the workspace's parent: traps write there
    shutil.copytree(
        task.repo, workspace, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache")
    )
    tracer = Tracer(run_dir / "trace.jsonl")
    tracer.event("eval_task", task=task.id, prompt=task.prompt)
    outcome = TaskOutcome(task.id, task.category, passed=False, reason="", trace=str(tracer.path))
    started = clock()
    try:
        agent = make_agent(workspace, task, tracer)
        result = agent.run(task.prompt)
    except Exception as exc:
        outcome.reason = f"agent error: {type(exc).__name__}: {exc}"
        outcome.seconds = round(clock() - started, 2)
        return outcome
    outcome.seconds = round(clock() - started, 2)
    outcome.stop_reason, outcome.steps, outcome.cost = result.stop_reason, result.steps, result.cost
    outcome.input_tokens, outcome.output_tokens = (
        result.usage.input_tokens,
        result.usage.output_tokens,
    )
    calls = [call for message in agent.history for call in message.tool_calls]
    ctx = EvalContext(workspace, task.repo, result.final_text, calls)
    try:
        outcome.passed, outcome.reason = load_check(task)(ctx)
    except Exception as exc:
        outcome.reason = f"check error: {type(exc).__name__}: {exc}"
    return outcome


def run_suite(
    tasks: list[EvalTask],
    make_agent: AgentFactory,
    scratch: Path,
    on_done: Callable[[TaskOutcome], None] | None = None,
) -> list[TaskOutcome]:
    outcomes = []
    for task in tasks:
        outcome = run_task(task, make_agent, scratch)
        outcomes.append(outcome)
        if on_done is not None:
            on_done(outcome)
    return outcomes


# --- Reporting ---------------------------------------------------------------------------------


def summarize(outcomes: list[TaskOutcome]) -> dict[str, Any]:
    count = len(outcomes) or 1
    costs = [o.cost for o in outcomes if o.cost is not None]
    return {
        "tasks": len(outcomes),
        "passed": sum(o.passed for o in outcomes),
        "pass_rate": round(sum(o.passed for o in outcomes) / count, 3),
        "avg_steps": round(sum(o.steps for o in outcomes) / count, 2),
        "input_tokens": sum(o.input_tokens for o in outcomes),
        "output_tokens": sum(o.output_tokens for o in outcomes),
        "cost": round(sum(costs), 4) if costs else None,
        "seconds": round(sum(o.seconds for o in outcomes), 1),
    }


def save_results(
    results_dir: Path, config: dict[str, Any], outcomes: list[TaskOutcome], label: str = ""
) -> Path:
    """Write `<stamp>-<model>-<label>.json`, with each task's trace copied next to it."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = "-".join(part for part in (stamp, str(config.get("model", "model")), label) if part)
    path = results_dir / f"{name.replace('/', '_')}.json"
    traces_dir = path.with_name(path.stem + "-traces")
    traces_dir.mkdir(parents=True, exist_ok=True)
    for outcome in outcomes:
        trace = Path(outcome.trace)
        if trace.is_file():
            target = traces_dir / f"{outcome.task_id}.jsonl"
            shutil.copyfile(trace, target)
            outcome.trace = target.relative_to(results_dir).as_posix()
    data = {
        "config": config,
        "label": label,
        "summary": summarize(outcomes),
        "tasks": [asdict(o) for o in outcomes],
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def results_table(outcomes: list[TaskOutcome], title: str = "Eval results") -> Table:
    table = Table(title=title)
    for column in (
        "task",
        "category",
        "result",
        "steps",
        "tokens in/out",
        "cost",
        "time",
        "reason",
    ):
        table.add_column(column)
    for o in outcomes:
        table.add_row(
            o.task_id,
            o.category,
            "[green]PASS[/]" if o.passed else "[red]FAIL[/]",
            str(o.steps),
            f"{o.input_tokens}/{o.output_tokens}",
            "n/a" if o.cost is None else f"${o.cost:.4f}",
            f"{o.seconds:.0f}s",
            o.reason[:60],
        )
    return table


def comparison_table(result_files: list[Path]) -> Table:
    """One column per results file: per-task PASS/FAIL, then the summary rows."""
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in result_files]
    table = Table(title="Eval comparison")
    table.add_column("task")
    for run in runs:
        table.add_column(f"{run['config'].get('model')} {run.get('label', '')}".strip())
    task_ids = sorted({t["task_id"] for run in runs for t in run["tasks"]})
    for task_id in task_ids:
        cells = []
        for run in runs:
            match = next((t for t in run["tasks"] if t["task_id"] == task_id), None)
            cells.append("-" if match is None else ("PASS" if match["passed"] else "FAIL"))
        table.add_row(task_id, *cells)
    for key in ("pass_rate", "avg_steps", "input_tokens", "output_tokens", "cost", "seconds"):
        table.add_row(f"[bold]{key}[/]", *[str(run["summary"].get(key)) for run in runs])
    return table


def print_table(table: Table, console: Console | None = None) -> None:
    (console or Console()).print(table)
