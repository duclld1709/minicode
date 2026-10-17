from pathlib import Path

import pytest

from minicode.config import ConfigError, load_settings
from minicode.llm.anthropic_client import AnthropicClient
from minicode.llm.factory import create_client
from minicode.llm.openai_client import OpenAIClient


@pytest.mark.m0
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


@pytest.mark.m1
def test_anthropic_provider_builds_anthropic_client(tmp_path: Path) -> None:
    env = {"MINICODE_PROVIDER": "anthropic", "MINICODE_MODEL": "m", "ANTHROPIC_API_KEY": "k"}
    client = create_client(load_settings(tmp_path, environ=env))
    assert isinstance(client, AnthropicClient)
    assert client.model == "m"


@pytest.mark.m1
def test_missing_key_for_selected_provider(tmp_path: Path) -> None:
    env = {"MINICODE_PROVIDER": "anthropic", "MINICODE_MODEL": "m", "OPENAI_API_KEY": "k"}
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        create_client(load_settings(tmp_path, environ=env))
