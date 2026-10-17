"""Fast, in-process MCP checks (no subprocess)."""

import asyncio
from pathlib import Path

import pytest
from mcp import Client, types

from minicode.mcp.client import result_text, tool_name
from minicode.mcp.server import build_server_registry, create_mcp_server

pytestmark = pytest.mark.m4


def test_tool_name_is_sanitized_and_bounded() -> None:
    assert tool_name("my server", "do.thing") == "mcp__my_server__do_thing"
    assert len(tool_name("s" * 50, "t" * 50)) == 64


def test_result_text_summarizes_non_text_blocks() -> None:
    result = types.CallToolResult(
        content=[
            types.TextContent(text="line"),
            types.ImageContent(data="AAAA", mime_type="image/png"),
        ]
    )
    assert result_text(result) == "line\n[image content omitted]"


def test_server_registry_never_includes_run_bash(tmp_path: Path) -> None:
    names = build_server_registry(tmp_path, allow_write=True).names
    assert "run_bash" not in names
    assert {"write_file", "edit_file"} <= set(names)


def test_in_process_server_round_trip(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha\n")
    server = create_mcp_server(build_server_registry(tmp_path, allow_write=False))

    async def scenario() -> tuple[list[str], types.CallToolResult]:
        async with Client(server) as client:
            listed = await client.list_tools()
            result = await client.call_tool("read_file", {"path": "a.txt"})
            return [t.name for t in listed.tools], result

    names, result = asyncio.run(scenario())
    assert sorted(names) == ["glob", "grep", "list_dir", "read_file"]
    assert not result.is_error
    assert "alpha" in result_text(result)
