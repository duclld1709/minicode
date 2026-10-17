"""Load tools from external MCP servers listed in `.minicode/mcp.json`.

Config format (same shape as Claude Code's):

    {
      "mcpServers": {
        "files": {"command": "uv", "args": ["run", "minicode", "mcp-serve"], "env": {}}
      }
    }

Each server's tools are registered as `mcp__<server>__<tool>` with risk "exec":
we cannot know what a third-party tool does, so it is treated as the riskiest
kind and goes through the permission prompt in `ask` and `accept-edits` modes.

Sync/async bridge: the MCP SDK is async, our tool handlers are plain functions.
Each `McpConnection` runs its own event loop in a background thread that keeps
the client session open; handlers submit coroutines to it and wait for results.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import TracebackType
from typing import Any

from mcp import Client, StdioServerParameters, types
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from minicode.config import ConfigError
from minicode.tools.base import Tool, ToolError

MCP_CONFIG_FILE = Path(".minicode") / "mcp.json"
DEFAULT_TIMEOUT_SECONDS = 60.0


class McpServerConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    # Only these variables (plus the SDK's safe defaults like PATH) reach the server.
    env: dict[str, str] | None = None
    cwd: str | None = None


class McpConfigFile(BaseModel):
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict, alias="mcpServers")


class AnyArguments(BaseModel):
    """Accepts any JSON object: the MCP server validates against its own schema."""

    model_config = ConfigDict(extra="allow")


def load_mcp_config(workspace: Path) -> dict[str, McpServerConfig]:
    """Read `.minicode/mcp.json`; a missing file simply means no MCP servers."""
    path = workspace / MCP_CONFIG_FILE
    if not path.is_file():
        return {}
    try:
        return McpConfigFile.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        ).mcp_servers
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ConfigError(f"Invalid {path}: {exc}") from exc


class McpConnection:
    """A live session with one MCP server, callable from synchronous code."""

    def __init__(self, config: McpServerConfig, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.params = StdioServerParameters(
            command=config.command, args=config.args, env=config.env, cwd=config.cwd
        )
        self.timeout = timeout
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._client: Client | None = None
        self._error: BaseException | None = None

    def start(self) -> None:
        """Launch the server and wait until the MCP handshake is done (or failed)."""
        self._thread.start()
        if not self._ready.wait(self.timeout):
            raise TimeoutError(f"MCP server did not start within {self.timeout}s")
        if self._error is not None:
            raise RuntimeError(f"MCP server failed to start: {self._error}") from self._error

    def list_tools(self) -> list[types.Tool]:
        return self._run(self._require_client().list_tools()).tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        return self._run(self._require_client().call_tool(name, arguments))

    def close(self) -> None:
        """Ask the background session to finish, then wait for the thread."""
        if not self._thread.is_alive() or self._loop is None or self._stop is None:
            return  # never started, or the session already ended (e.g. server crashed)
        # The loop may close between the check above and now: then there is nothing to stop.
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(self.timeout)

    # --- background thread -----------------------------------------------------------

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._session())
        except BaseException as exc:  # reported to start() through _error
            self._error = exc
        finally:
            self._ready.set()

    async def _session(self) -> None:
        # The client must be entered and exited in the same task, so this coroutine
        # owns it for the whole connection and just waits for close().
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        async with Client(self.params) as client:
            self._client = client
            self._ready.set()
            await self._stop.wait()

    def _run[T](self, coroutine: Coroutine[Any, Any, T]) -> T:
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(self.timeout)

    def _require_client(self) -> Client:
        if self._client is None:
            raise RuntimeError("MCP connection is not started")
        return self._client


def tool_name(server: str, tool: str) -> str:
    """`mcp__<server>__<tool>`, reduced to the characters and length providers accept."""
    name = f"mcp__{server}__{tool}"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64]


def result_text(result: types.CallToolResult) -> str:
    """Flatten MCP content blocks to text; non-text blocks are summarized."""
    parts = [
        block.text if isinstance(block, types.TextContent) else f"[{block.type} content omitted]"
        for block in result.content
    ]
    return "\n".join(parts)


def tools_from_connection(server: str, connection: McpConnection) -> list[Tool]:
    """Wrap every tool the server offers as a minicode Tool."""

    def make_handler(remote_name: str) -> Callable[[AnyArguments], str]:
        def handler(args: AnyArguments) -> str:
            result = connection.call_tool(remote_name, args.model_dump())
            text = result_text(result)
            if result.is_error:
                raise ToolError(text or f"MCP tool '{remote_name}' reported an error.")
            return text

        return handler

    return [
        Tool(
            name=tool_name(server, remote.name),
            description=f"[MCP server '{server}'] {remote.description or ''}".strip(),
            input_model=AnyArguments,
            handler=make_handler(remote.name),
            risk="exec",
            input_schema=remote.input_schema,
        )
        for remote in connection.list_tools()
    ]


class McpManager:
    """Starts all configured servers and closes them on exit (use as a context manager).

    A server that fails to start is reported in `errors` and skipped: one broken
    third-party server should not prevent the agent from running.
    """

    def __init__(self, configs: dict[str, McpServerConfig]) -> None:
        self.configs = configs
        self.connections: list[McpConnection] = []
        self.tools: list[Tool] = []
        self.errors: list[str] = []

    def __enter__(self) -> McpManager:
        for name, config in self.configs.items():
            connection = McpConnection(config)
            try:
                connection.start()
                self.tools.extend(tools_from_connection(name, connection))
                self.connections.append(connection)
            except Exception as exc:
                connection.close()
                self.errors.append(f"MCP server '{name}': {exc}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        for connection in self.connections:
            connection.close()
