"""Assemble the default toolbelt for a workspace."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from minicode.tools.base import ToolRegistry
from minicode.tools.fs import FileTools
from minicode.tools.shell import ShellTool, find_bash


def build_registry(
    root: Path,
    *,
    environ: Mapping[str, str],
    bash: str | None = None,
) -> ToolRegistry:
    """Registry with the filesystem tools and run_bash, all bound to `root`.

    `environ` is passed in (not read from os.environ) so tests control exactly
    what the shell sees.
    """
    registry = ToolRegistry()
    for tool in FileTools(root).tools():
        registry.register(tool)
    shell = ShellTool(root, bash=bash or find_bash(environ), environ=environ)
    registry.register(shell.tool())
    return registry
