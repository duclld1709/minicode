"""The LLMClient Protocol: the only interface the rest of minicode depends on."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from minicode.llm.types import LLMResponse, Message

TextCallback = Callable[[str], None]
"""Receives text as it is generated. Adapters that do not stream call it once."""


@runtime_checkable
class LLMClient(Protocol):
    """Anything that can turn a conversation into the next model turn.

    Why a Protocol and not a base class: adapters (and test fakes) do not need to
    inherit from anything; they only need the right shape. That keeps the fake
    client trivial and avoids coupling adapters to a shared parent.

    `model` is exposed so callers can estimate cost and label traces.
    `on_text` is part of the contract from M0 so that adding streaming in M1 does
    not change the interface (see MILESTONES.md, "Interface changes").
    """

    model: str

    def complete(
        self,
        messages: list[Message],
        *,
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
        on_text: TextCallback | None = None,
    ) -> LLMResponse: ...
