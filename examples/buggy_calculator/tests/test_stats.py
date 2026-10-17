import pytest
from calculator.stats import mean, median


def test_mean() -> None:
    assert mean([1, 2, 3, 4]) == 2.5


def test_mean_of_empty_list() -> None:
    with pytest.raises(ValueError):
        mean([])


def test_median_odd() -> None:
    assert median([3, 1, 2]) == 2


def test_median_even() -> None:
    assert median([4, 1, 3, 2]) == 2.5
