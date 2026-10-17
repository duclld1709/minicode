import pytest
from listutils import chunk, flatten


def test_chunk_even() -> None:
    assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_chunk_with_remainder() -> None:
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_empty() -> None:
    assert chunk([], 3) == []


def test_chunk_bigger_than_list() -> None:
    assert chunk([1, 2], 5) == [[1, 2]]


def test_chunk_rejects_bad_size() -> None:
    with pytest.raises(ValueError):
        chunk([1], 0)


def test_flatten_round_trip() -> None:
    assert flatten(chunk([1, 2, 3, 4, 5], 3)) == [1, 2, 3, 4, 5]
