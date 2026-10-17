"""Pick and build the right LLMClient from Settings.

This is the only place that knows which adapter class goes with which provider,
so switching providers is purely a configuration change.
"""

from __future__ import annotations

from minicode.config import Settings
from minicode.llm.base import LLMClient


def create_client(settings: Settings, *, small: bool = False) -> LLMClient:
    """Build a client for the main model, or for the small model when `small=True`."""
    model = settings.effective_small_model if small else settings.model
    # Adapters are imported here, not at module level: the provider SDKs take
    # seconds to import, and commands like `mcp-serve` never need them.
    if settings.provider == "openai":
        from minicode.llm.openai_client import OpenAIClient

        return OpenAIClient(model, api_key=settings.api_key())
    from minicode.llm.anthropic_client import AnthropicClient

    return AnthropicClient(model, api_key=settings.api_key())
