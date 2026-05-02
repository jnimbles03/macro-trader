"""Sizing formula floors at zero contracts when max_loss > budget."""

import os

from app.analysis.sizing import size_spread, size_yolo


def _set_account(size: str | None):
    if size is None:
        os.environ.pop("DEFAULT_ACCOUNT_SIZE", None)
    else:
        os.environ["DEFAULT_ACCOUNT_SIZE"] = size
    from app.config import reload_settings
    reload_settings()


def test_size_spread_floors_to_zero_when_max_loss_too_big():
    _set_account("100000")
    # 0.50% of 100k = $500 budget. max_loss $1500 → floor 0
    r = size_spread(1500.0)
    assert r.contracts == 0


def test_size_spread_normal_case():
    _set_account("100000")
    r = size_spread(250.0)                # $500 budget / $250 per spread = 2 contracts
    assert r.contracts == 2
    assert r.risk_dollars == 500.0


def test_size_yolo_normal_case():
    _set_account("100000")
    # 0.25% of 100k = $250 budget; $400 premium per contract → 0
    r = size_yolo(400.0)
    assert r.contracts == 0
    # $200 premium → 1
    r = size_yolo(200.0)
    assert r.contracts == 1


def test_no_account_size_returns_manual_note():
    _set_account(None)
    r = size_spread(250.0)
    assert r.contracts == 0
    assert r.risk_dollars is None
    assert "size manually" in r.note.lower()
    _set_account("100000")
