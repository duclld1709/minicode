"""Rough cost estimation from token usage.

Prices change often, so this table is *data*, not logic: override or extend it in
`.minicode/config.toml` under `[pricing."<model-id>"]`. Unknown models get no
estimate (None) rather than a wrong number.
"""

from __future__ import annotations

from pydantic import BaseModel

from minicode.llm.types import Usage


class Price(BaseModel):
    """USD per 1 million tokens."""

    input_per_mtok: float
    output_per_mtok: float


# Standard-tier list prices, short-context tier, checked 2026-10-17 against
# https://developers.openai.com/api/docs/pricing and
# https://platform.claude.com/docs/en/about-claude/pricing
# Ignores prompt-cache discounts and long-context surcharges: this is an estimate.
DEFAULT_PRICES: dict[str, Price] = {
    # OpenAI
    "gpt-6.1-sol": Price(input_per_mtok=2.00, output_per_mtok=10.00),
    "gpt-6-sol": Price(input_per_mtok=2.00, output_per_mtok=10.00),
    "gpt-6-luna": Price(input_per_mtok=0.10, output_per_mtok=0.50),
    "gpt-5.5": Price(input_per_mtok=5.00, output_per_mtok=30.00),
    # Anthropic
    "claude-opus-5-5": Price(input_per_mtok=4.00, output_per_mtok=20.00),
    "claude-sonnet-5-5": Price(input_per_mtok=2.00, output_per_mtok=10.00),
    "claude-haiku-5-5": Price(input_per_mtok=0.10, output_per_mtok=0.50),
}


def estimate_cost(model: str, usage: Usage, prices: dict[str, Price]) -> float | None:
    """Return the estimated USD cost of `usage` for `model`, or None if the price is unknown."""
    price = prices.get(model)
    if price is None:
        return None
    return (
        usage.input_tokens * price.input_per_mtok + usage.output_tokens * price.output_per_mtok
    ) / 1_000_000
