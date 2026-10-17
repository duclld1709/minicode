import pytest

from minicode.llm.pricing import Price, estimate_cost
from minicode.llm.types import Usage

pytestmark = pytest.mark.m0

PRICES = {"m": Price(input_per_mtok=2.0, output_per_mtok=10.0)}


def test_cost_is_per_million_tokens() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000)
    assert estimate_cost("m", usage, PRICES) == pytest.approx(2.0 + 1.0)


def test_unknown_model_has_no_estimate() -> None:
    assert estimate_cost("unknown", Usage(input_tokens=5, output_tokens=5), PRICES) is None
