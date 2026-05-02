"""Test config — force MOCK_DATA on by default."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("MOCK_DATA", "true")
os.environ.setdefault("PAPER_MODE", "true")
os.environ.setdefault("DEFAULT_ACCOUNT_SIZE", "100000")
os.environ.setdefault("MIN_OPTION_VOLUME", "50")
os.environ.setdefault("MIN_OPEN_INTEREST", "100")


@pytest.fixture(autouse=True)
def _reload_settings():
    from app.config import reload_settings
    reload_settings()
    yield
