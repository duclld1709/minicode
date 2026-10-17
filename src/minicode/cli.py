"""Command-line entry points (typer).

The CLI is a thin shell: it loads settings, builds objects (`build_agent`), and
hands them to plain functions (`chat_loop`, `agent_repl`) that take their
dependencies as arguments, so the interesting logic is testable without a
terminal or network. Rendering lives in `ui.py`.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from minicode.agent.context import Compactor
from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.loop import Agent, AgentListener, AgentResult
from minicode.agent.prompts import PromptContext, build_system_prompt, read_git_status
from minicode.agent.router import Router
from minicode.chat import ChatSession
from minicode.config import ConfigError, Settings, load_settings
from minicode.harness.memory import load_project_memory
from minicode.harness.skills import discover_skills, make_skill_tool
from minicode.llm.base import LLMClient
from minicode.llm.factory import create_client
from minicode.llm.types import Usage
from minicode.mcp.client import McpManager, load_mcp_config
from minicode.mcp.server import serve_stdio
from minicode.tools.base import Tool, ToolError
from minicode.tools.shell import ShellTool, find_bash
from minicode.tools.todo import TodoList
from minicode.tools.toolbelt import build_registry
from minicode.tracing import (
    TRACES_DIR,
    FanoutListener,
    TracedLLM,
    TraceListener,
    Tracer,
    latest_trace,
    load_trace,
    new_trace_path,
    preview,
)
from minicode.ui import RichListener, format_summary, make_permission_prompt, render_trace
from minicode.workflows.commit_msg import NoChangesError, read_diff, write_commit_message
from minicode.workflows.subagent import DelegateTool
from minicode.workflows.verifier import run_with_verification

app = typer.Typer(help="minicode: a mini coding agent built from scratch.", add_completion=False)


class Mode(StrEnum):
    ask = "ask"
    accept_edits = "accept-edits"
    auto = "auto"


CwdOption = Annotated[
    Path, typer.Option("--cwd", help="Workspace directory.", exists=True, file_okay=False)
]
ModeOption = Annotated[
    Mode, typer.Option("--mode", help="ask: confirm writes and commands; accept-edits; auto.")
]
MaxStepsOption = Annotated[int, typer.Option("--max-steps", min=1, help="LLM calls per task.")]
MaxCostOption = Annotated[
    float | None, typer.Option("--max-cost", help="Stop a task after this many USD.")
]

RouteOption = Annotated[
    bool, typer.Option("--route/--no-route", help="Classify tasks; questions get read-only tools.")
]

EXIT_COMMANDS = {"/exit", "/quit"}


@dataclass
class RunOptions:
    """CLI choices that shape the agent (grouped so build_agent stays readable)."""

    mode: Mode = Mode.ask
    max_steps: int = 30
    max_cost: float | None = None
    route: bool = True


# --- Agent commands --------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    cwd: CwdOption = Path("."),
    mode: ModeOption = Mode.ask,
    max_steps: MaxStepsOption = 30,
    max_cost: MaxCostOption = None,
    route: RouteOption = True,
) -> None:
    """Start the interactive agent (REPL) when no subcommand is given."""
    if ctx.invoked_subcommand is not None:
        return
    console = Console()
    settings = _load_settings_or_exit(cwd, console)
    options = RunOptions(mode, max_steps, max_cost, route)
    tracer = open_tracer(cwd, settings, options)
    with mcp_tools(cwd, console) as extra_tools:
        agent = build_agent(settings, cwd, console, options, extra_tools, tracer)
        console.print(f"[dim]minicode | {agent.llm.model} | mode {mode.value} | /exit to quit[/]")
        agent_repl(agent, console, lambda: console.input("[bold green]task>[/] "), tracer)
    console.print(f"[dim]Trace: {tracer.path}[/]")


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="What the agent should do.")],
    cwd: CwdOption = Path("."),
    mode: ModeOption = Mode.ask,
    max_steps: MaxStepsOption = 30,
    max_cost: MaxCostOption = None,
    route: RouteOption = True,
    verify: Annotated[
        str | None, typer.Option("--verify", help='Check command, e.g. "pytest -q".')
    ] = None,
    max_verify_rounds: Annotated[
        int, typer.Option("--max-verify-rounds", min=1, help="Verification attempts.")
    ] = 3,
) -> None:
    """Run one task to completion, then exit (code 0 only if it completed and verified)."""
    console = Console()
    settings = _load_settings_or_exit(cwd, console)
    options = RunOptions(mode, max_steps, max_cost, route)
    tracer = open_tracer(cwd, settings, options)
    with mcp_tools(cwd, console) as extra_tools:
        agent = build_agent(settings, cwd, console, options, extra_tools, tracer)
        if verify is None:
            result = run_task(agent, task, console, tracer)
            ok = result is not None and result.stop_reason == "completed"
        else:
            ok = run_verified_task(agent, task, console, verify, max_verify_rounds, cwd, tracer)
    console.print(f"[dim]Trace: {tracer.path}[/]")
    raise typer.Exit(code=0 if ok else 1)


@app.command()
def replay(
    trace: Annotated[
        Path | None, typer.Argument(help="Trace file (default: the latest in --cwd).")
    ] = None,
    cwd: CwdOption = Path("."),
) -> None:
    """Pretty-print a session trace (.minicode/traces/*.jsonl)."""
    console = Console()
    path = trace or latest_trace(cwd)
    if path is None or not path.is_file():
        console.print(Text(f"No trace found ({path or cwd / TRACES_DIR}).", style="red"))
        raise typer.Exit(code=1)
    console.print(Text(f"Trace: {path}", style="dim"))
    render_trace(load_trace(path), console)


def open_tracer(cwd: Path, settings: Settings, options: RunOptions) -> Tracer:
    """One trace file per session. API keys are masked in every line written."""
    keys = [
        k.get_secret_value() for k in (settings.openai_api_key, settings.anthropic_api_key) if k
    ]
    tracer = Tracer(new_trace_path(cwd), secrets=keys)
    tracer.event(
        "session_start",
        provider=settings.provider,
        model=settings.model,
        small_model=settings.effective_small_model,
        cwd=str(cwd.resolve()),
        mode=options.mode.value,
        route=options.route,
    )
    return tracer


def run_verified_task(
    agent: Agent,
    task: str,
    console: Console,
    command: str,
    max_rounds: int,
    cwd: Path,
    tracer: Tracer | None = None,
) -> bool:
    """Evaluator-optimizer: run, check with `command`, feed failures back."""
    shell = ShellTool(cwd, bash=find_bash(os.environ), environ=os.environ)

    def run_check(check: str) -> tuple[int, str]:
        try:
            return shell.run(check, timeout_seconds=600)
        except ToolError as exc:
            return 1, str(exc)

    def on_check(exit_code: int, output: str) -> None:
        if tracer is not None:
            tracer.event("verify", command=command, exit_code=exit_code, output=preview(output))
        _end_stream(agent)
        if exit_code == 0:
            console.print(Text.assemble(("[verify passed] ", "green"), command))
        else:
            console.print(Text.assemble((f"[verify failed, exit {exit_code}] ", "red"), command))

    try:
        verified = run_with_verification(
            agent,
            task,
            command=command,
            run_check=run_check,
            max_rounds=max_rounds,
            on_check=on_check,
        )
    except Exception as exc:
        _print_error(console, "Error", exc)
        return False
    _end_stream(agent)
    status = "verified" if verified.verified else "NOT verified"
    console.print(
        Text(
            f"{status} after {verified.rounds} check(s) | all runs: in "
            f"{verified.usage.input_tokens} out {verified.usage.output_tokens} | "
            f"last run: {format_summary(verified.result)}",
            style="green" if verified.verified else "yellow",
        )
    )
    return verified.verified


@app.command("commit-msg")
def commit_msg(cwd: CwdOption = Path(".")) -> None:
    """Prompt chaining: summarize the current git diff, then write a commit message for it."""
    console = Console()
    settings = _load_settings_or_exit(cwd, console)
    try:
        llm = create_client(settings, small=True)  # a cheap, well-defined task
        diff = read_diff(cwd)
    except (ConfigError, NoChangesError) as exc:
        _print_error(console, "Error", exc)
        raise typer.Exit(code=1) from exc
    try:
        result = write_commit_message(llm, diff)
    except Exception as exc:
        _print_error(console, "Error", exc)
        raise typer.Exit(code=1) from exc
    console.print(Text(result.message))
    usage = result.usage
    console.print(
        Text(f"[2 calls | in {usage.input_tokens} | out {usage.output_tokens}]", style="dim")
    )


@app.command("mcp-serve")
def mcp_serve(
    cwd: CwdOption = Path("."),
    allow_write: Annotated[
        bool, typer.Option("--allow-write", help="Also expose write_file and edit_file.")
    ] = False,
) -> None:
    """Serve minicode's filesystem tools over MCP (stdio). Read-only unless --allow-write."""
    serve_stdio(cwd, allow_write=allow_write)


@contextmanager
def mcp_tools(cwd: Path, console: Console) -> Iterator[list[Tool]]:
    """Start the MCP servers from `.minicode/mcp.json` for the duration of the block."""
    try:
        configs = load_mcp_config(cwd)
    except ConfigError as exc:
        _print_error(console, "Config error", exc)
        raise typer.Exit(code=2) from exc
    with McpManager(configs) as manager:
        for error in manager.errors:
            console.print(Text(f"Warning: {error}", style="yellow"))
        if manager.tools:
            console.print(f"[dim]Loaded {len(manager.tools)} MCP tool(s).[/]")
        yield manager.tools


def build_agent(
    settings: Settings,
    cwd: Path,
    console: Console,
    options: RunOptions,
    extra_tools: list[Tool] | None = None,
    tracer: Tracer | None = None,
) -> Agent:
    """Wire the real dependencies together. Tests build Agents directly instead."""
    try:
        llm: LLMClient = create_client(settings)
        small_llm: LLMClient = create_client(settings, small=True)
    except ConfigError as exc:
        _print_error(console, "Config error", exc)
        raise typer.Exit(code=2) from exc
    listener: AgentListener = RichListener(console)
    if tracer is not None:
        llm = TracedLLM(llm, tracer, label="main", prices=settings.pricing)
        small_llm = TracedLLM(small_llm, tracer, label="small", prices=settings.pricing)
        listener = FanoutListener(listener, TraceListener(tracer))
    permission = PermissionPolicy(
        mode=options.mode.value,
        prompt=make_permission_prompt(console, read_answer=lambda: console.input("")),
    )
    skills = discover_skills(cwd)
    delegate = DelegateTool(llm, cwd, max_tokens=settings.max_tokens)
    registry = build_registry(cwd, environ=os.environ)
    for tool in [*TodoList().tools(), delegate.tool(), *(extra_tools or [])]:
        registry.register(tool)
    if skills:
        registry.register(make_skill_tool(skills))
    context = PromptContext(
        workspace=cwd,
        today=date.today(),
        git_status=read_git_status(cwd),
        project_memory=load_project_memory(cwd),
        skills=skills,
    )
    agent = Agent(
        llm,
        registry,
        Guards(max_steps=options.max_steps, max_cost_usd=options.max_cost),
        permission=permission,
        system=build_system_prompt(context),
        listener=listener,
        max_tokens=settings.max_tokens,
        prices=settings.pricing,
        compactor=Compactor(small_llm, threshold_tokens=settings.compact_at_tokens),
        router=Router(small_llm) if options.route else None,
    )
    delegate.on_usage = agent.add_usage  # subagent tokens count toward this agent's budget
    return agent


def run_task(
    agent: Agent, task: str, console: Console, tracer: Tracer | None = None
) -> AgentResult | None:
    """Run one task and print its summary. Provider errors are shown, not raised."""
    if tracer is not None:
        tracer.event("run_start", task=task)
    started = time.perf_counter()
    try:
        result = agent.run(task)
    except Exception as exc:
        _print_error(console, "Error", exc)
        if tracer is not None:
            tracer.event("error", message=short_error(exc))
        return None
    _end_stream(agent)
    if tracer is not None:
        tracer.event(
            "run_end",
            stop_reason=result.stop_reason,
            steps=result.steps,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost=result.cost,
            wall_ms=round((time.perf_counter() - started) * 1000),
        )
    style = "green" if result.stop_reason == "completed" else "yellow"
    console.print(Text(format_summary(result), style=style))
    return result


def agent_repl(
    agent: Agent, console: Console, read_line: Callable[[], str], tracer: Tracer | None = None
) -> None:
    """One conversation, many tasks. Ctrl+C during a task stops the task, not the REPL."""
    while True:
        try:
            task = read_line().strip()
        except (EOFError, KeyboardInterrupt):
            break
        if task in EXIT_COMMANDS:
            break
        if task:
            run_task(agent, task, console, tracer)
    console.print("[dim]Bye.[/]")


# --- Plain chat (M0) ----------------------------------------------------------------------


@app.command()
def chat(cwd: CwdOption = Path(".")) -> None:
    """Multi-turn chat with the configured model (no tools)."""
    console = Console()
    settings = _load_settings_or_exit(cwd, console)
    try:
        llm = create_client(settings)
    except ConfigError as exc:
        _print_error(console, "Config error", exc)
        raise typer.Exit(code=2) from exc
    session = ChatSession(llm, max_tokens=settings.max_tokens, prices=settings.pricing)
    console.print(f"[dim]minicode chat | {settings.provider}:{llm.model} | /exit to quit[/]")
    chat_loop(session, console, read_line=lambda: console.input("[bold cyan]you>[/] "))


def chat_loop(session: ChatSession, console: Console, read_line: Callable[[], str]) -> None:
    """Read-eval-print loop. Ctrl+D / Ctrl+C at the prompt or /exit ends it."""
    while True:
        try:
            text = read_line().strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text in EXIT_COMMANDS:
            break
        try:
            response = session.send(text, on_text=_stream_printer(console))
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/]")
            continue
        except Exception as exc:  # show a short message, keep the session alive
            console.print()
            _print_error(console, "Error", exc)
            continue
        console.print()  # end the streamed line
        console.print(
            format_usage(response.usage, session.cost_of(response.usage), session.total_cost),
            style="dim",
        )
    console.print("[dim]Bye.[/]")


def _stream_printer(console: Console) -> Callable[[str], None]:
    """Print text chunks as they arrive, verbatim (no Markdown: it needs the whole reply)."""

    def print_chunk(chunk: str) -> None:
        console.print(chunk, end="", markup=False, highlight=False)

    return print_chunk


# --- Helpers ---------------------------------------------------------------------------------


def format_usage(usage: Usage, cost: float | None, session_cost: float | None) -> str:
    """One status line, e.g. `in 120 | out 45 | $0.0007 | session $0.0031`."""
    return (
        f"in {usage.input_tokens} | out {usage.output_tokens} | "
        f"{_money(cost)} | session {_money(session_cost)}"
    )


def short_error(exc: Exception, limit: int = 300) -> str:
    """A one-line error summary; full tracebacks would bury the useful part."""
    message = f"{type(exc).__name__}: {exc}"
    return message if len(message) <= limit else message[:limit] + "..."


def _money(value: float | None) -> str:
    return "cost n/a" if value is None else f"${value:.4f}"


def _end_stream(agent: Agent) -> None:
    """Finish a half-printed streamed line before printing something else."""
    end_line = getattr(agent.listener, "end_line", None)  # RichListener or FanoutListener
    if end_line is not None:
        end_line()


def _print_error(console: Console, label: str, exc: Exception) -> None:
    # Text, not markup: exception messages may contain brackets.
    console.print(Text.assemble((f"{label}: ", "red"), short_error(exc)))


def _load_settings_or_exit(cwd: Path, console: Console) -> Settings:
    try:
        return load_settings(cwd, environ=os.environ, dotenv_file=Path.cwd() / ".env")
    except ConfigError as exc:
        _print_error(console, "Config error", exc)
        raise typer.Exit(code=2) from exc
