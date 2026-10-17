"""Pick and build the right LLMClient from Settings.

This is the only place that knows which adapter class goes with which provider,
so switching providers is purely a configuration change.
"""

from __future__ import annotations

from minicode.config import ConfigError, Settings
from minicode.llm.base import LLMClient
from minicode.llm.openai_client import OpenAIClient


def create_client(settings: Settings, *, small: bool = False) -> LLMClient:
    """Build a client for the main model, or for the small model when `small=True`."""
    model = settings.effective_small_model if small else settings.model
    if settings.provider == "openai":
        return OpenAIClient(model, api_key=settings.api_key())
    raise ConfigError(
        f"Provider '{settings.provider}' is not implemented yet (the Anthropic adapter "
        "arrives in M1). Set MINICODE_PROVIDER=openai for now."
    )
