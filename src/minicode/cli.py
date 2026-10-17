"""Command-line entry points (typer) and terminal rendering (rich).

The CLI is a thin shell: it loads settings, builds objects, and hands them to
plain functions (like `chat_loop`) that take their dependencies as arguments, so
the interesting logic is testable without a terminal or network.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown

from minicode.chat import ChatSession
from minicode.config import ConfigError, Settings, load_settings
from minicode.llm.factory import create_client
from minicode.llm.types import Usage

app = typer.Typer(
    help="minicode: a mini coding agent built from scratch.",
    no_args_is_help=True,
    add_completion=False,
)

CwdOption = Annotated[
    Path,
    typer.Option("--cwd", help="Workspace directory.", exists=True, file_okay=False),
]

EXIT_COMMANDS = {"/exit", "/quit"}


@app.callback()
def main() -> None:
    """minicode: a mini coding agent built from scratch."""
    # An explicit callback keeps `chat` as a named subcommand even while it is the only one.


@app.command()
def chat(cwd: CwdOption = Path(".")) -> None:
    """Multi-turn chat with the configured model (no tools)."""
    console = Console()
    settings = _load_settings_or_exit(cwd, console)
    try:
        llm = create_client(settings)
    except ConfigError as exc:
        console.print(f"[red]Config error:[/] {exc}")
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
            response = session.send(text)
        except KeyboardInterrupt:
            console.print("[yellow]Interrupted.[/]")
            continue
        except Exception as exc:  # show a short message, keep the session alive
            console.print(f"[red]Error:[/] {short_error(exc)}")
            continue
        console.print(Markdown(response.text))
        console.print(
            format_usage(response.usage, session.cost_of(response.usage), session.total_cost),
            style="dim",
        )
    console.print("[dim]Bye.[/]")


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


def _load_settings_or_exit(cwd: Path, console: Console) -> Settings:
    try:
        return load_settings(cwd, environ=os.environ, dotenv_file=Path.cwd() / ".env")
    except ConfigError as exc:
        console.print(f"[red]Config error:[/] {exc}")
        raise typer.Exit(code=2) from exc
