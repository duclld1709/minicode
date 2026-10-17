"""Shared pytest setup.

Live tests (marker `live`) call real provider APIs and cost money, so they run
only when explicitly requested with `--run-live` *and* a key is configured.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Run tests marked `live` (real API calls, costs money).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="live test: pass --run-live to enable")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
