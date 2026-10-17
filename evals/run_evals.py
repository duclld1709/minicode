"""Run minicode's eval suite, or compare saved results.

    uv run python evals/run_evals.py --model gpt-6.1-sol
    uv run python evals/run_evals.py --model claude-sonnet-5-5 --provider anthropic --label baseline
    uv run python evals/run_evals.py --tasks fix_calculator,question_config --no-route
    uv run python evals/run_evals.py --compare evals/results/a.json evals/results/b.json

Each task runs in a fresh temp copy of its fixture, in `auto` permission mode
(there is no one to ask), with the same toolbelt, prompt and guards as
`minicode run`. Results (JSON) and one trace per task are saved to evals/results/.
The logic lives in `minicode.evals`; this file only parses arguments and wires
the real agent in.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from rich.console import Console

from minicode.agent.loop import Agent
from minicode.cli import Mode, RunOptions, build_agent
from minicode.config import ConfigError, Settings, load_settings
from minicode.evals import (
    AgentFactory,
    EvalTask,
    TaskOutcome,
    comparison_table,
    load_tasks,
    results_table,
    run_suite,
    save_results,
    summarize,
)
from minicode.llm.factory import create_client
from minicode.tracing import Tracer

EVALS_DIR = Path(__file__).parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--model", help="Main model id (overrides MINICODE_MODEL).")
    parser.add_argument("--small-model", help="Small model id (overrides MINICODE_SMALL_MODEL).")
    parser.add_argument(
        "--provider", choices=["openai", "anthropic"], help="Overrides MINICODE_PROVIDER."
    )
    parser.add_argument("--tasks", help="Comma-separated task ids (default: all).")
    parser.add_argument("--label", default="", help="Name for this configuration in the results.")
    parser.add_argument("--no-route", action="store_true", help="Disable task routing.")
    parser.add_argument("--max-cost", type=float, default=1.0, help="USD budget per task.")
    parser.add_argument("--results-dir", type=Path, default=EVALS_DIR / "results")
    parser.add_argument("--compare", nargs="+", type=Path, help="Compare saved result files.")
    return parser.parse_args()


def load_eval_settings(args: argparse.Namespace) -> Settings:
    overrides = {
        "MINICODE_MODEL": args.model,
        "MINICODE_SMALL_MODEL": args.small_model,
        "MINICODE_PROVIDER": args.provider,
    }
    environ = {**os.environ, **{k: v for k, v in overrides.items() if v}}
    settings = load_settings(Path("."), environ=environ, dotenv_file=Path(".env"))
    create_client(settings)  # fail fast on a missing key, before running anything
    return settings


def agent_factory(settings: Settings, args: argparse.Namespace) -> AgentFactory:
    def make(workspace: Path, task: EvalTask, tracer: Tracer) -> Agent:
        options = RunOptions(
            mode=Mode.auto,
            max_steps=task.max_steps,
            max_cost=args.max_cost,
            route=not args.no_route,
        )
        return build_agent(settings, workspace, Console(quiet=True), options, tracer=tracer)

    return make


def main() -> int:
    args = parse_args()
    console = Console()
    if args.compare:
        Console(width=160).print(comparison_table(args.compare))
        return 0
    try:
        settings = load_eval_settings(args)
    except ConfigError as exc:
        console.print(f"[red]Config error:[/] {exc}")
        return 2
    tasks = load_tasks(EVALS_DIR / "tasks", args.tasks.split(",") if args.tasks else None)
    console.print(f"Running {len(tasks)} task(s) with {settings.provider}:{settings.model}")

    def report(outcome: TaskOutcome) -> None:
        status = "[green]PASS[/]" if outcome.passed else "[red]FAIL[/]"
        stats = f"({outcome.steps} steps, {outcome.seconds:.0f}s)"
        console.print(f"  {status} {outcome.task_id} {stats} {outcome.reason}")

    with tempfile.TemporaryDirectory(prefix="minicode-evals-") as scratch:
        outcomes = run_suite(tasks, agent_factory(settings, args), Path(scratch), on_done=report)
        config = {
            "provider": settings.provider,
            "model": settings.model,
            "small_model": settings.effective_small_model,
            "route": not args.no_route,
            "max_cost_per_task": args.max_cost,
        }
        path = save_results(args.results_dir, config, outcomes, args.label)
    wide = Console(width=160)  # rich defaults to 80 columns when output is not a terminal
    wide.print(results_table(outcomes, title=f"{settings.model} {args.label}".strip()))
    console.print(summarize(outcomes))
    console.print(f"Saved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
