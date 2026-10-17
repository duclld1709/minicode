"""Command-line entry points (typer).

The CLI is a thin shell: it loads settings, builds objects (`build_agent`), and
hands them to plain functions (`chat_loop`, `agent_repl`) that take their
dependencies as arguments, so the interesting logic is testable without a
terminal or network. Rendering lives in `ui.py`.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from minicode.agent.context import Compactor
from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.loop import Agent, AgentResult
from minicode.agent.prompts import PromptContext, build_system_prompt, read_git_status
from minicode.chat import ChatSession
from minicode.config import ConfigError, Settings, load_settings
from minicode.harness.memory import load_project_memory
from minicode.harness.skills import discover_skills, make_skill_tool
from minicode.llm.factory import create_client
from minicode.llm.types import Usage
from minicode.mcp.client import McpManager, load_mcp_config
from minicode.mcp.server import serve_stdio
from minicode.tools.base import Tool
from minicode.tools.toolbelt import build_registry
from minicode.ui import RichListener, format_summary, make_permission_prompt

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

EXIT_COMMANDS = {"/exit", "/quit"}


# --- Agent commands --------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    cwd: CwdOption = Path("."),
    mode: ModeOption = Mode.ask,
    max_steps: MaxStepsOption = 30,
    max_cost: MaxCostOption = None,
) -> None:
    """Start the interactive agent (REPL) when no subcommand is given."""
    if ctx.invoked_subcommand is not None:
        return
    console = Console()
    settings = _load_settings_or_exit(cwd, console)
    with mcp_tools(cwd, console) as extra_tools:
        agent = build_agent(settings, cwd, console, mode, max_steps, max_cost, extra_tools)
        console.print(f"[dim]minicode | {agent.llm.model} | mode {mode.value} | /exit to quit[/]")
        agent_repl(agent, console, read_line=lambda: console.input("[bold green]task>[/] "))


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="What the agent should do.")],
    cwd: CwdOption = Path("."),
    mode: ModeOption = Mode.ask,
    max_steps: MaxStepsOption = 30,
    max_cost: MaxCostOption = None,
) -> None:
    """Run one task to completion, then exit (code 0 only if it completed)."""
    console = Console()
    settings = _load_settings_or_exit(cwd, console)
    with mcp_tools(cwd, console) as extra_tools:
        agent = build_agent(settings, cwd, console, mode, max_steps, max_cost, extra_tools)
        result = run_task(agent, task, console)
    raise typer.Exit(code=0 if result is not None and result.stop_reason == "completed" else 1)


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
    mode: Mode,
    max_steps: int,
    max_cost: float | None,
    extra_tools: list[Tool] | None = None,
) -> Agent:
    """Wire the real dependencies together. Tests build Agents directly instead."""
    try:
        llm = create_client(settings)
        small_llm = create_client(settings, small=True)
    except ConfigError as exc:
        _print_error(console, "Config error", exc)
        raise typer.Exit(code=2) from exc
    permission = PermissionPolicy(
        mode=mode.value,
        prompt=make_permission_prompt(console, read_answer=lambda: console.input("")),
    )
    skills = discover_skills(cwd)
    registry = build_registry(cwd, environ=os.environ)
    if skills:
        registry.register(make_skill_tool(skills))
    for tool in extra_tools or []:
        registry.register(tool)
    context = PromptContext(
        workspace=cwd,
        today=date.today(),
        git_status=read_git_status(cwd),
        project_memory=load_project_memory(cwd),
        skills=skills,
    )
    return Agent(
        llm,
        registry,
        Guards(max_steps=max_steps, max_cost_usd=max_cost),
        permission=permission,
        system=build_system_prompt(context),
        listener=RichListener(console),
        max_tokens=settings.max_tokens,
        prices=settings.pricing,
        compactor=Compactor(small_llm, threshold_tokens=settings.compact_at_tokens),
    )


def run_task(agent: Agent, task: str, console: Console) -> AgentResult | None:
    """Run one task and print its summary. Provider errors are shown, not raised."""
    try:
        result = agent.run(task)
    except Exception as exc:
        _print_error(console, "Error", exc)
        return None
    if isinstance(agent.listener, RichListener):
        agent.listener.end_line()
    style = "green" if result.stop_reason == "completed" else "yellow"
    console.print(Text(format_summary(result), style=style))
    return result


def agent_repl(agent: Agent, console: Console, read_line: Callable[[], str]) -> None:
    """One conversation, many tasks. Ctrl+C during a task stops the task, not the REPL."""
    while True:
        try:
            task = read_line().strip()
        except (EOFError, KeyboardInterrupt):
            break
        if task in EXIT_COMMANDS:
            break
        if task:
            run_task(agent, task, console)
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


def _print_error(console: Console, label: str, exc: Exception) -> None:
    # Text, not markup: exception messages may contain brackets.
    console.print(Text.assemble((f"{label}: ", "red"), short_error(exc)))


def _load_settings_or_exit(cwd: Path, console: Console) -> Settings:
    try:
        return load_settings(cwd, environ=os.environ, dotenv_file=Path.cwd() / ".env")
    except ConfigError as exc:
        _print_error(console, "Config error", exc)
        raise typer.Exit(code=2) from exc
