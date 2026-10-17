"""Allow `python -m minicode ...` (used to launch our own MCP server in tests)."""

from minicode.cli import app

app(prog_name="minicode")
