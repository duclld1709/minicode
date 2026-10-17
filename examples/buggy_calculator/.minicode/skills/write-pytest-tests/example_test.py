"""Template for the write-pytest-tests skill (not collected: lives outside tests/)."""

import pytest
from calculator.stats import median


@pytest.mark.parametrize(
    ("values", "expected"),
    [([3, 1, 2], 2), ([4, 1, 3, 2], 2.5), ([7], 7)],
)
def test_median(values: list[float], expected: float) -> None:
    assert median(values) == pytest.approx(expected)


def test_median_of_empty_list_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        median([])
