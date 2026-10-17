"""Temperature conversions."""


def c_to_f(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def f_to_c(fahrenheit: float) -> float:
    return (fahrenheit - 32) * 5 / 9


def c_to_k(celsius: float) -> float:
    return celsius + 273.15
