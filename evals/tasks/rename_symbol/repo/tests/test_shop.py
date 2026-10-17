from shop import calc_total
from shop.cart import Cart
from shop.report import order_line


def test_calc_total_with_tax() -> None:
    assert calc_total([10.0, 5.0], tax_rate=0.1) == 16.5


def test_cart_total() -> None:
    cart = Cart()
    cart.add(2.5)
    cart.add(2.5)
    assert cart.total() == 5.0


def test_order_line() -> None:
    assert order_line("alice", [1.0, 2.0]) == "alice: 3.00"
