"""One real tool-use round trip: the provider must accept our schemas and tool results."""

import os
from pathlib import Path

import pytest

from minicode.config import ConfigError, load_settings
from minicode.llm.factory import create_client
from minicode.llm.types import Message
from minicode.tools.toolbelt import build_registry

pytestmark = [pytest.mark.live, pytest.mark.m2]


def test_model_reads_a_file_with_read_file(tmp_path: Path) -> None:
    try:
        settings = load_settings(Path("."), environ=os.environ, dotenv_file=Path(".env"))
        llm = create_client(settings)
    except ConfigError as exc:
        pytest.skip(f"not configured: {exc}")
    (tmp_path / "notes.txt").write_text("The deploy password hint is: BLUE-HERON\n")
    registry = build_registry(tmp_path, environ={})
    history = [Message.user("Use the read_file tool on notes.txt and tell me the hint.")]

    first = llm.complete(history, system="", tools=registry.schemas(), max_tokens=1000)
    assert first.tool_calls, f"expected a tool call, got text: {first.text!r}"
    assert first.tool_calls[0].name == "read_file"

    history.append(Message.assistant(first))
    history.append(Message.tool([registry.execute(c) for c in first.tool_calls]))
    final = llm.complete(history, system="", tools=registry.schemas(), max_tokens=1000)

    assert "BLUE-HERON" in final.text.upper()
