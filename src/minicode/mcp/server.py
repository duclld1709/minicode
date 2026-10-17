"""`minicode mcp-serve`: expose minicode's filesystem tools over MCP (stdio).

The server is a thin adapter around the same `ToolRegistry` the agent uses:
`tools/list` returns `registry.schemas()` and `tools/call` goes through
`registry.execute()`. So schemas, the workspace sandbox and the "never raise,
explain the error" behaviour are identical for MCP clients and for our agent.

We use the SDK's low-level `Server` (handlers for list/call) rather than the
decorator-based `MCPServer`, because our tools already have JSON schemas; the
decorator API would re-derive them from Python signatures.

Try it with the MCP Inspector:
    npx @modelcontextprotocol/inspector uv run minicode mcp-serve --cwd .
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from minicode.llm.types import ToolCall
from minicode.tools.base import ToolRegistry
from minicode.tools.fs import FileTools

SERVER_NAME = "minicode"


def build_server_registry(root: Path, *, allow_write: bool) -> ToolRegistry:
    """Filesystem tools only (never run_bash); write tools only when explicitly allowed."""
    registry = ToolRegistry()
    for tool in FileTools(root).tools():
        if tool.risk == "read" or allow_write:
            registry.register(tool)
    return registry


def create_mcp_server(registry: ToolRegistry) -> Server[Any]:
    """Wrap a ToolRegistry in an MCP server."""

    async def list_tools(
        ctx: Any, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        tools = [
            types.Tool(name=s["name"], description=s["description"], input_schema=s["input_schema"])
            for s in registry.schemas()
        ]
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        call = ToolCall(id="mcp", name=params.name, arguments=params.arguments or {})
        # Tool handlers are synchronous (file I/O); run them off the event loop.
        result = await anyio.to_thread.run_sync(registry.execute, call)
        return types.CallToolResult(
            content=[types.TextContent(text=result.content)], is_error=result.is_error
        )

    return Server(SERVER_NAME, on_list_tools=list_tools, on_call_tool=call_tool)


def serve_stdio(root: Path, *, allow_write: bool) -> None:
    """Block and serve MCP over stdin/stdout until the client disconnects.

    Nothing else may write to stdout while serving: stdout *is* the protocol.
    """
    server = create_mcp_server(build_server_registry(root, allow_write=allow_write))

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(run)
