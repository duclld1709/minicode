"""Simple statistics over lists of numbers."""


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean of empty list")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    if not values:
        raise ValueError("median of empty list")
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle]
