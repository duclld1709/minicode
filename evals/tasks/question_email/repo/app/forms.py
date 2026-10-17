"""Signup form handling."""

from app.validators import is_valid_email, is_valid_username


def clean_email(raw: str) -> str:
    # Normalizes only; validation happens in validators.py.
    return raw.strip().lower()


def signup_errors(username: str, email: str) -> list[str]:
    errors = []
    if not is_valid_username(username):
        errors.append("invalid username")
    if not is_valid_email(clean_email(email)):
        errors.append("invalid email")
    return errors
