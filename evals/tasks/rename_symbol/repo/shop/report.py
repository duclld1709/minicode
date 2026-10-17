"""Order reports."""

from shop import pricing


def order_line(name: str, prices: list[float]) -> str:
    return f"{name}: {pricing.calc_total(prices):.2f}"
