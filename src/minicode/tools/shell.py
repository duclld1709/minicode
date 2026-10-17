"""The run_bash tool.

Runs one command with `bash -c` in the workspace, with a timeout, and returns the
combined stdout+stderr plus the exit code. A non-zero exit code is *not* a tool
error: a failing `pytest` is exactly the information the agent asked for.

Safety in M2: timeout, output truncation (by the registry), and API keys removed
from the child environment so a command like `env` cannot leak them. The command
denylist and the permission prompt arrive in M3, which is where risky actions
are gated.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, Field

from minicode.tools.base import Tool, ToolError

SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")

RUN_BASH_DOC = (
    "Run a bash command in the workspace root and return its output and exit code. Use it "
    "for running tests, linters, git, and other CLI tools. Commands are non-interactive (no "
    "stdin). Prefer the file tools for reading, searching and editing files."
)


class RunBashArgs(BaseModel):
    command: str = Field(description="The bash command to run, e.g. 'uv run pytest -q'.")
    timeout_seconds: int = Field(
        default=120, ge=1, le=600, description="Kill the command after this many seconds."
    )


def find_bash(environ: Mapping[str, str]) -> str | None:
    """Locate a bash executable.

    `MINICODE_BASH` wins. On Windows, `bash` on PATH is usually the WSL launcher
    (System32), which runs in a different filesystem, so Git Bash next to git.exe
    is preferred.
    """
    if environ.get("MINICODE_BASH"):
        return environ["MINICODE_BASH"]
    if os.name == "nt":
        git = shutil.which("git")
        if git is not None:
            candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    return shutil.which("bash")


def scrubbed_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Copy of the environment without anything that looks like a credential."""
    return {
        key: value
        for key, value in environ.items()
        if not any(marker in key.upper() for marker in SECRET_MARKERS)
    }


class ShellTool:
    """run_bash bound to one workspace root."""

    def __init__(self, root: Path, *, bash: str | None, environ: Mapping[str, str]) -> None:
        self.root = root.resolve()
        self.bash = bash
        self.env = scrubbed_env(environ)

    def tool(self) -> Tool:
        return Tool("run_bash", RUN_BASH_DOC, RunBashArgs, self.run_bash, "exec")

    def run_bash(self, args: RunBashArgs) -> str:
        exit_code, output = self.run(args.command, args.timeout_seconds)
        return f"{output or '(no output)'}\n[exit code: {exit_code}]"

    def run(self, command: str, timeout_seconds: float) -> tuple[int, str]:
        """Run `command` and return (exit code, combined output). Also used by --verify."""
        if self.bash is None:
            raise ToolError("bash was not found on this machine. Set MINICODE_BASH to its path.")
        try:
            completed = subprocess.run(
                [self.bash, "-c", command],
                cwd=self.root,
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # one stream keeps errors next to their context
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            partial = _decode(exc.output)
            raise ToolError(
                f"Command timed out after {timeout_seconds}s and was killed. "
                f"Partial output:\n{partial}"
            ) from exc
        return completed.returncode, _decode(completed.stdout).rstrip()


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")
