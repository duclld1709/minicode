"""Input validation."""

import re

# local part, "@", domain, ".", then a top-level domain of at least 2 lowercase letters
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")


def is_valid_email(address: str) -> bool:
    return EMAIL_RE.match(address) is not None


def is_valid_username(name: str) -> bool:
    return 3 <= len(name) <= 20 and name.isalnum()
