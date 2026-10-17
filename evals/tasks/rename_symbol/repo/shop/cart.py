"""Shopping cart."""

from shop.pricing import calc_total


class Cart:
    def __init__(self) -> None:
        self.prices: list[float] = []

    def add(self, price: float) -> None:
        self.prices.append(price)

    def total(self, tax_rate: float = 0.0) -> float:
        return calc_total(self.prices, tax_rate)
