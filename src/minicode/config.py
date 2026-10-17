"""Settings loading.

Precedence (later wins): `.minicode/config.toml` in the workspace < `.env` file <
real environment variables. Keeping this explicit (no magic settings library)
makes it easy to see where a value came from.

Nothing here touches `os.environ` or module-level state: callers pass the
environment in, which keeps tests hermetic.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, ValidationError

from minicode.llm.pricing import DEFAULT_PRICES, Price

Provider = Literal["anthropic", "openai"]

ENV_TO_FIELD: dict[str, str] = {
    "MINICODE_PROVIDER": "provider",
    "MINICODE_MODEL": "model",
    "MINICODE_SMALL_MODEL": "small_model",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "OPENAI_API_KEY": "openai_api_key",
}

CONFIG_FILE = Path(".minicode") / "config.toml"


class ConfigError(Exception):
    """A configuration problem the user can fix; the message says how."""


class Settings(BaseModel):
    provider: Provider
    model: str
    # Used for cheap side tasks (summaries, routing). Falls back to `model`.
    small_model: str | None = None
    # SecretStr keeps keys out of reprs, logs and tracebacks.
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    max_tokens: int = 4096
    pricing: dict[str, Price] = Field(default_factory=lambda: dict(DEFAULT_PRICES))

    @property
    def effective_small_model(self) -> str:
        return self.small_model or self.model

    def api_key(self) -> str:
        """Return the key for the selected provider, or explain how to set it."""
        secret = self.openai_api_key if self.provider == "openai" else self.anthropic_api_key
        if secret is None:
            var = "OPENAI_API_KEY" if self.provider == "openai" else "ANTHROPIC_API_KEY"
            raise ConfigError(f"{var} is not set (provider is '{self.provider}'). Add it to .env.")
        return secret.get_secret_value()


def load_settings(
    workspace: Path,
    *,
    environ: Mapping[str, str],
    dotenv_file: Path | None = None,
) -> Settings:
    """Build Settings from the workspace config file, a .env file and the environment."""
    values = _read_config_file(workspace / CONFIG_FILE)
    if dotenv_file is not None and dotenv_file.is_file():
        dotenv = {k: v for k, v in dotenv_values(dotenv_file).items() if v is not None}
        values.update(_from_env(dotenv))
    values.update(_from_env(environ))
    return _validate(values)


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc
    # Prices in the file extend/override the defaults rather than replacing them.
    if "pricing" in data:
        data["pricing"] = {**DEFAULT_PRICES, **data["pricing"]}
    return data


def _from_env(env: Mapping[str, str]) -> dict[str, Any]:
    # Empty strings (e.g. `MINICODE_MODEL=` copied from .env.example) count as unset.
    return {field: env[var] for var, field in ENV_TO_FIELD.items() if env.get(var)}


def _validate(values: dict[str, Any]) -> Settings:
    # Model IDs are deliberately not defaulted in code: they go stale. See .env.example.
    required = {"MINICODE_PROVIDER": "provider", "MINICODE_MODEL": "model"}
    missing = [var for var, field in required.items() if field not in values]
    if missing:
        raise ConfigError(
            f"Missing required setting(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill them in."
        )
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        raise ConfigError(f"Invalid settings: {exc}") from exc
