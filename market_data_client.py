"""Thin market data client — use this in all other Python projects.

Usage:
    from market_data_client import get_quote, get_chain, subscribe

    quote = get_quote("EEM")
    chain = get_chain("EEM", "2026-11-21")
    subscribe("NVDA")  # ad-hoc, expires 24h

Set MARKET_DATA_URL env var to override (default: http://100.126.133.54:8001).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_BASE = os.environ.get("MARKET_DATA_URL", "http://100.126.133.54:8001").rstrip("/")
_TIMEOUT = 10.0


def get_quote(ticker: str) -> dict[str, Any]:
    """Latest price for ticker. Returns dict with 'price' and 'updated_at'."""
    r = httpx.get(f"{_BASE}/api/v1/quote/{ticker}", timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_chain(ticker: str, expiry: str = "front") -> dict[str, Any]:
    """Option chain. expiry: 'YYYY-MM-DD' or 'front' for front-month.

    Returns dict with 'contracts' list, each with:
    type, strike, bid, ask, iv, delta, gamma, theta, vega, volume
    """
    r = httpx.get(f"{_BASE}/api/v1/chain/{ticker}/{expiry}", timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def subscribe(ticker: str, *, sec_type: str = "STK", expiry: str | None = None,
              requested_by: str | None = None, ttl_hours: int = 24) -> dict[str, Any]:
    """Register a ticker for ad-hoc ingest. Expires after ttl_hours."""
    params: dict[str, Any] = {
        "sec_type": sec_type,
        "ttl_hours": ttl_hours,
    }
    if expiry:
        params["expiry"] = expiry
    if requested_by:
        params["requested_by"] = requested_by
    r = httpx.post(f"{_BASE}/api/v1/subscribe/{ticker}", params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_watchlist() -> list[dict[str, Any]]:
    r = httpx.get(f"{_BASE}/api/v1/watchlist", timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json().get("watchlist", [])


def get_status() -> dict[str, Any]:
    r = httpx.get(f"{_BASE}/api/v1/status", timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()
