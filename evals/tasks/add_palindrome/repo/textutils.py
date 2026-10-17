"""Text helpers."""

import re


def slugify(text: str) -> str:
    """'Hello, World!' -> 'hello-world'."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words)
