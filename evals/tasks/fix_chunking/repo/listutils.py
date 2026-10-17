"""Small helpers for lists."""


def chunk(items: list[int], size: int) -> list[list[int]]:
    """Split `items` into consecutive chunks of length `size`; the last one may be shorter."""
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i : i + size] for i in range(0, len(items) - size, size)]


def flatten(nested: list[list[int]]) -> list[int]:
    return [item for sublist in nested for item in sublist]
