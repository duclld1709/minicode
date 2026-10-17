from pathlib import Path

import pytest

from minicode.config import ConfigError, load_settings
from minicode.llm.factory import create_client
from minicode.llm.openai_client import OpenAIClient

pytestmark = pytest.mark.m0


def test_openai_provider_builds_openai_client(tmp_path: Path) -> None:
    env = {
        "MINICODE_PROVIDER": "openai",
        "MINICODE_MODEL": "main",
        "MINICODE_SMALL_MODEL": "small",
        "OPENAI_API_KEY": "sk-test",
    }
    settings = load_settings(tmp_path, environ=env)

    main = create_client(settings)
    small = create_client(settings, small=True)

    assert isinstance(main, OpenAIClient)
    assert (main.model, small.model) == ("main", "small")


def test_anthropic_is_not_available_yet(tmp_path: Path) -> None:
    env = {"MINICODE_PROVIDER": "anthropic", "MINICODE_MODEL": "m", "ANTHROPIC_API_KEY": "k"}
    with pytest.raises(ConfigError, match="M1"):
        create_client(load_settings(tmp_path, environ=env))
