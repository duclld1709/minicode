"""Runtime settings, read from the environment."""

import os

DEFAULT_PORT = 8420
DEFAULT_HOST = "127.0.0.1"


def port() -> int:
    return int(os.environ.get("APP_PORT", DEFAULT_PORT))


def host() -> str:
    return os.environ.get("APP_HOST", DEFAULT_HOST)
