"""Integration/contract tests for MCP (M4).

minicode's own MCP server is started as a real subprocess
(`python -m minicode mcp-serve --cwd <workspace>`), and the client side loads its
tools exactly as it would load any third-party server from `.minicode/mcp.json`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from minicode.agent.guards import Guards, PermissionPolicy
from minicode.agent.loop import Agent
from minicode.config import ConfigError
from minicode.llm.fake_client import FakeLLMClient, tool_call_response
from minicode.llm.types import ToolCall, ToolResult
from minicode.mcp.client import McpManager, McpServerConfig, load_mcp_config
from minicode.tools.base import Tool, ToolRegistry

pytestmark = pytest.mark.m4

READ_ONLY = {"read_file", "list_dir", "glob", "grep"}


def server_config(workspace: Path, *extra_args: str) -> McpServerConfig:
    args = ["-m", "minicode", "mcp-serve", "--cwd", str(workspace), *extra_args]
    return McpServerConfig(command=sys.executable, args=args)


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("mcp_ws")
    (root / "hello.txt").write_text("hello from MCP\n")
    return root


@pytest.fixture(scope="module")
def manager(workspace: Path) -> Iterator[McpManager]:
    with McpManager({"files": server_config(workspace)}) as started:
        yield started


@pytest.fixture(scope="module")
def registry(manager: McpManager) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in manager.tools:
        registry.register(tool)
    return registry


def call(registry: ToolRegistry, name: str, **arguments: object) -> ToolResult:
    return registry.execute(ToolCall(id="c1", name=name, arguments=arguments))


def remote_names(tools: list[Tool]) -> set[str]:
    return {t.name.removeprefix("mcp__files__") for t in tools}


def test_server_starts_and_exposes_read_only_tools(manager: McpManager) -> None:
    assert manager.errors == []
    assert remote_names(manager.tools) == READ_ONLY


def test_tools_are_namespaced_and_treated_as_exec(manager: McpManager) -> None:
    for tool in manager.tools:
        assert tool.name.startswith("mcp__files__")
        assert tool.risk == "exec"  # unknown third-party code: most cautious level


def test_schemas_come_from_the_server(registry: ToolRegistry) -> None:
    schema = next(s for s in registry.schemas() if s["name"] == "mcp__files__read_file")
    assert "path" in schema["input_schema"]["properties"]


def test_call_a_tool_through_mcp(registry: ToolRegistry) -> None:
    result = call(registry, "mcp__files__read_file", path="hello.txt")
    assert not result.is_error
    assert "hello from MCP" in result.content


def test_errors_cross_the_wire_as_tool_errors(registry: ToolRegistry) -> None:
    missing = call(registry, "mcp__files__read_file", path="nope.txt")
    assert missing.is_error
    assert "not found" in missing.content.lower()
    escape = call(registry, "mcp__files__read_file", path="../outside.txt")
    assert escape.is_error
    assert "outside the workspace" in escape.content


def test_allow_write_exposes_write_tools(tmp_path: Path) -> None:
    with McpManager({"files": server_config(tmp_path, "--allow-write")}) as writable:
        assert {"write_file", "edit_file"} <= remote_names(writable.tools)
        write = next(t for t in writable.tools if t.name == "mcp__files__write_file")
        registry = ToolRegistry()
        registry.register(write)
        result = call(registry, write.name, path="new.txt", content="written via MCP\n")
    assert not result.is_error
    assert (tmp_path / "new.txt").read_text() == "written via MCP\n"


def test_agent_uses_mcp_tool_and_asks_permission(registry: ToolRegistry) -> None:
    asked: list[str] = []

    def prompt(tool_call: ToolCall, tool: Tool) -> str:
        asked.append(tool.name)
        return "yes"

    read = ToolCall(id="c1", name="mcp__files__read_file", arguments={"path": "hello.txt"})
    llm = FakeLLMClient(script=[tool_call_response([read]), "It says hello."])
    policy = PermissionPolicy(mode="accept-edits", prompt=prompt)  # type: ignore[arg-type]
    result = Agent(llm, registry, Guards(), permission=policy).run("read hello.txt")

    assert result.stop_reason == "completed"
    assert asked == ["mcp__files__read_file"]  # exec risk: asked even in accept-edits
    assert "hello from MCP" in llm.calls[1].messages[-1].tool_results[0].content


def test_broken_server_is_reported_not_fatal() -> None:
    config = McpServerConfig(command=sys.executable, args=["-c", "import sys; sys.exit(1)"])
    with McpManager({"broken": config}) as manager:
        assert manager.tools == []
        assert len(manager.errors) == 1
        assert "broken" in manager.errors[0]


def test_load_mcp_config(tmp_path: Path) -> None:
    assert load_mcp_config(tmp_path) == {}
    (tmp_path / ".minicode").mkdir()
    config = {"mcpServers": {"files": {"command": "uv", "args": ["run", "minicode", "mcp-serve"]}}}
    (tmp_path / ".minicode" / "mcp.json").write_text(json.dumps(config))
    loaded = load_mcp_config(tmp_path)
    assert loaded["files"].command == "uv"
    assert loaded["files"].args == ["run", "minicode", "mcp-serve"]


def test_invalid_mcp_config_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / ".minicode").mkdir()
    (tmp_path / ".minicode" / "mcp.json").write_text("{not json")
    with pytest.raises(ConfigError):
        load_mcp_config(tmp_path)
