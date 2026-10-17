import pytest
from calculator import add, divide, median


def test_add() -> None:
    assert add(2, 3) == 5


def test_divide() -> None:
    assert divide(7, 2) == 3.5


def test_divide_by_zero() -> None:
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)


def test_median_odd() -> None:
    assert median([3, 1, 2]) == 2


def test_median_even() -> None:
    assert median([4, 1, 3, 2]) == 2.5
