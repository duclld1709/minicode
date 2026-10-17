"""Real API call. Runs only with `pytest --run-live` and a configured provider + key."""

import os
from pathlib import Path

import pytest

from minicode.chat import ChatSession
from minicode.config import ConfigError, load_settings
from minicode.llm.factory import create_client

pytestmark = [pytest.mark.live, pytest.mark.m0]


def test_two_turn_chat_remembers_context() -> None:
    try:
        settings = load_settings(Path("."), environ=os.environ, dotenv_file=Path(".env"))
        llm = create_client(settings)
    except ConfigError as exc:
        pytest.skip(f"not configured: {exc}")

    session = ChatSession(llm, max_tokens=200, prices=settings.pricing)
    session.send("Remember this codeword: PELICAN. Reply with just 'ok'.")
    reply = session.send("What was the codeword? Reply with just the word.")

    assert "PELICAN" in reply.text.upper()
    assert session.total_usage.input_tokens > 0
