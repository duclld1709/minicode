"""Entry point."""

from server import settings

LEGACY_PORT = 8000  # used by the old deployment scripts only; not the default


def address() -> str:
    return f"{settings.host()}:{settings.port()}"
