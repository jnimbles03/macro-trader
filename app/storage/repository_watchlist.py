"""Watchlist repository — ad-hoc ticker subscriptions."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.storage.db import make_engine, _engine_url


def _is_postgres() -> bool:
    return _engine_url().startswith("postgresql")


def subscribe(ticker: str, *, sec_type: str = "STK", expiry: str | None = None,
              requested_by: str | None = None, ttl_hours: int = 24) -> dict:
    now = datetime.now(tz=timezone.utc)
    expires = now + timedelta(hours=ttl_hours)
    params = {
        "ticker": ticker.upper(),
        "sec_type": sec_type.upper(),
        "expiry": expiry,
        "requested_by": requested_by,
        "created_at": now,
        "expires_at": expires,
    }
    eng = make_engine()
    with eng.begin() as conn:
        if _is_postgres():
            conn.execute(text("""
                INSERT INTO watchlist (ticker, sec_type, expiry, requested_by, created_at, expires_at)
                VALUES (:ticker, :sec_type, :expiry, :requested_by, :created_at, :expires_at)
                ON CONFLICT (ticker, sec_type) DO UPDATE
                SET expires_at = EXCLUDED.expires_at,
                    requested_by = EXCLUDED.requested_by
            """), params)
        else:
            conn.execute(text("""
                INSERT OR REPLACE INTO watchlist
                    (ticker, sec_type, expiry, requested_by, created_at, expires_at)
                VALUES (:ticker, :sec_type, :expiry, :requested_by, :created_at, :expires_at)
            """), params)
    return {"ticker": ticker.upper(), "expires_at": expires.isoformat()}


def active_watchlist() -> list[dict]:
    now = datetime.now(tz=timezone.utc)
    eng = make_engine()
    with eng.begin() as conn:
        rows = conn.execute(text("""
            SELECT ticker, sec_type, expiry, requested_by, expires_at
            FROM watchlist WHERE expires_at > :now ORDER BY ticker
        """), {"now": now}).fetchall()
    return [
        {"ticker": r[0], "sec_type": r[1], "expiry": r[2],
         "requested_by": r[3], "expires_at": str(r[4])}
        for r in rows
    ]


def purge_expired() -> int:
    now = datetime.now(tz=timezone.utc)
    eng = make_engine()
    with eng.begin() as conn:
        result = conn.execute(text(
            "DELETE FROM watchlist WHERE expires_at <= :now"
        ), {"now": now})
        return result.rowcount or 0
