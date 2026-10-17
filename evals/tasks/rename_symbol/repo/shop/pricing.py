"""Price calculations."""


def calc_total(prices: list[float], tax_rate: float = 0.0) -> float:
    """Sum of prices plus tax, rounded to cents."""
    return round(sum(prices) * (1 + tax_rate), 2)
