import pytest
from discount import apply_discount


def test_ten_percent_off() -> None:
    assert apply_discount(200.0, 10) == 180.0


def test_no_discount() -> None:
    assert apply_discount(50.0, 0) == 50.0


def test_invalid_percent() -> None:
    with pytest.raises(ValueError):
        apply_discount(10.0, 150)
