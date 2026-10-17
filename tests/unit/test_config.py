from pathlib import Path

import pytest

from minicode.config import ConfigError, load_settings

pytestmark = pytest.mark.m0

BASE_ENV = {"MINICODE_PROVIDER": "openai", "MINICODE_MODEL": "model-a"}


def test_loads_from_environ(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, environ=BASE_ENV)
    assert settings.provider == "openai"
    assert settings.model == "model-a"


def test_small_model_falls_back_to_main_model(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, environ=BASE_ENV)
    assert settings.effective_small_model == "model-a"


def test_missing_model_is_a_helpful_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="MINICODE_MODEL"):
        load_settings(tmp_path, environ={"MINICODE_PROVIDER": "openai"})


def test_empty_string_counts_as_unset(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="MINICODE_MODEL"):
        load_settings(tmp_path, environ={**BASE_ENV, "MINICODE_MODEL": ""})


def test_unknown_provider_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_settings(tmp_path, environ={**BASE_ENV, "MINICODE_PROVIDER": "gemini"})


def test_precedence_config_file_then_dotenv_then_environ(tmp_path: Path) -> None:
    (tmp_path / ".minicode").mkdir()
    (tmp_path / ".minicode" / "config.toml").write_text(
        'provider = "openai"\n'
        'model = "from-file"\n'
        'small_model = "small-from-file"\n'
        "max_tokens = 123\n"
    )
    dotenv = tmp_path / ".env"
    dotenv.write_text("MINICODE_MODEL=from-dotenv\nMINICODE_SMALL_MODEL=small-from-dotenv\n")

    settings = load_settings(
        tmp_path, environ={"MINICODE_SMALL_MODEL": "small-from-env"}, dotenv_file=dotenv
    )

    assert settings.max_tokens == 123  # only in the file
    assert settings.model == "from-dotenv"  # .env beats the file
    assert settings.small_model == "small-from-env"  # real env beats .env


def test_config_file_pricing_extends_defaults(tmp_path: Path) -> None:
    (tmp_path / ".minicode").mkdir()
    (tmp_path / ".minicode" / "config.toml").write_text(
        '[pricing."my-model"]\ninput_per_mtok = 1.0\noutput_per_mtok = 2.0\n'
    )
    settings = load_settings(tmp_path, environ=BASE_ENV)
    assert settings.pricing["my-model"].output_per_mtok == 2.0
    assert "gpt-6.1-sol" in settings.pricing


def test_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / ".minicode").mkdir()
    (tmp_path / ".minicode" / "config.toml").write_text("not = [valid")
    with pytest.raises(ConfigError, match="Invalid TOML"):
        load_settings(tmp_path, environ=BASE_ENV)


def test_api_key_is_secret_and_required(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, environ={**BASE_ENV, "OPENAI_API_KEY": "sk-secret"})
    assert "sk-secret" not in repr(settings)
    assert settings.api_key() == "sk-secret"

    no_key = load_settings(tmp_path, environ=BASE_ENV)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        no_key.api_key()
