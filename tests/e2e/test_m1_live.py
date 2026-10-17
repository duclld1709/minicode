"""Real API calls for M1, against whichever provider is configured.

Run with `uv run pytest --run-live -m live`. Switch provider with MINICODE_PROVIDER.
"""

import os
from pathlib import Path

import pytest
from pydantic import BaseModel

from minicode.config import ConfigError, Settings, load_settings
from minicode.llm.base import LLMClient
from minicode.llm.factory import create_client
from minicode.llm.structured import complete_structured
from minicode.llm.types import Message

pytestmark = [pytest.mark.live, pytest.mark.m1]


def configured(small: bool = False) -> tuple[Settings, LLMClient]:
    try:
        settings = load_settings(Path("."), environ=os.environ, dotenv_file=Path(".env"))
        return settings, create_client(settings, small=small)
    except ConfigError as exc:
        pytest.skip(f"not configured: {exc}")


def test_streaming_text_arrives_in_chunks() -> None:
    _, llm = configured()
    chunks: list[str] = []
    result = llm.complete(
        [Message.user("Count from 1 to 20, separated by spaces. Nothing else.")],
        system="",
        tools=[],
        max_tokens=500,
        on_text=chunks.append,
    )
    assert len(chunks) > 1
    assert "".join(chunks) == result.text
    assert "20" in result.text


class Classification(BaseModel):
    kind: str
    reason: str


def test_structured_output_with_small_model() -> None:
    _, llm = configured(small=True)
    result = complete_structured(
        llm,
        "Classify the task 'rename function foo to bar in utils.py'. "
        "kind must be either 'question' or 'edit'.",
        Classification,
    )
    assert result.kind == "edit"
