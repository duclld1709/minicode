"""`minicode run` picks up `.minicode/mcp.json` and the agent can call those tools."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from minicode import cli
from minicode.llm.fake_client import FakeLLMClient, tool_call_response
from minicode.llm.types import ToolCall

pytestmark = pytest.mark.m4


def test_run_loads_mcp_tools_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "remote.txt").write_text("content from the other workspace\n")
    workspace = tmp_path / "ws"
    (workspace / ".minicode").mkdir(parents=True)
    server = {
        "command": sys.executable,
        "args": ["-m", "minicode", "mcp-serve", "--cwd", str(served)],
    }
    (workspace / ".minicode" / "mcp.json").write_text(json.dumps({"mcpServers": {"other": server}}))

    monkeypatch.chdir(tmp_path)
    for var, value in {
        "MINICODE_PROVIDER": "openai",
        "MINICODE_MODEL": "m",
        "OPENAI_API_KEY": "k",
    }.items():
        monkeypatch.setenv(var, value)
    read = ToolCall(id="c1", name="mcp__other__read_file", arguments={"path": "remote.txt"})
    llm = FakeLLMClient(script=[tool_call_response([read]), "Done."])

    def fake_create_client(settings: Any, small: bool = False) -> FakeLLMClient:
        return llm

    monkeypatch.setattr(cli, "create_client", fake_create_client)

    result = CliRunner().invoke(
        cli.app, ["run", "read it", "--cwd", str(workspace), "--mode", "auto"]
    )

    assert result.exit_code == 0, result.output
    assert "Loaded 4 MCP tool(s)" in result.output
    assert "content from the other workspace" in llm.calls[1].messages[-1].tool_results[0].content
