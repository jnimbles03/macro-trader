"""External market data API — v1 router.

Endpoints:
  GET /api/v1/status
  GET /api/v1/quote/{ticker}
  GET /api/v1/chain/{ticker}/{expiry}      expiry = YYYY-MM-DD or "front" or "all"
  GET /api/v1/expirations/{ticker}
  POST /api/v1/subscribe/{ticker}
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import redis as _redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.storage.db import make_engine

router = APIRouter(prefix="/api/v1", tags=["market-data-v1"])

# Redis connection (optional — gracefully degrades if unavailable)
def _redis_client():
    try:
        url = os.getenv("REDIS_URL")
        if url:
            r = _redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        else:
            host = os.getenv("REDIS_HOST", "localhost")
            port = int(os.getenv("REDIS_PORT", 6379))
            r = _redis.Redis(host=host, port=port, decode_responses=True, socket_connect_timeout=2)
        r.ping()
        return r
    except Exception:
        return None


# ── Status ───────────────────────────────────────────────────────────────────

@router.get("/status")
def status() -> JSONResponse:
    r = _redis_client()
    eng = make_engine()
    db_ok = False
    chain_count = 0
    headline_count = 0
    try:
        with eng.connect() as conn:
            db_ok = True
            chain_count = conn.execute(text("SELECT COUNT(*) FROM option_chains")).scalar() or 0
            try:
                headline_count = conn.execute(text("SELECT COUNT(*) FROM headlines")).scalar() or 0
            except Exception:
                pass
    except Exception:
        pass

    return JSONResponse({
        "redis": "connected" if r else "unavailable",
        "db": "connected" if db_ok else "error",
        "chains_stored": chain_count,
        "headlines_stored": headline_count,
        "timestamp": datetime.utcnow().isoformat(),
    })


# ── Quote ────────────────────────────────────────────────────────────────────

@router.get("/quote/{ticker}")
def quote(ticker: str) -> JSONResponse:
    ticker = ticker.upper()

    # 1. Check Redis hot cache first
    r = _redis_client()
    if r:
        cached = r.hgetall(f"quote:{ticker}")
        if cached:
            return JSONResponse(cached)

    # 2. Fall back to latest chain from DB
    eng = make_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(text("""
                SELECT underlying_price, quote_time
                FROM option_chains
                WHERE root = :t
                ORDER BY quote_time DESC
                LIMIT 1
            """), {"t": ticker}).fetchone()
        if row and row[0]:
            payload = {
                "ticker": ticker,
                "price": float(row[0]),
                "source": "warehouse",
                "as_of": str(row[1]),
            }
            if r:
                r.hset(f"quote:{ticker}", mapping=payload)
                r.expire(f"quote:{ticker}", 60)
            return JSONResponse(payload)
    except Exception as e:
        pass

    return JSONResponse({"error": f"No data for {ticker}"}, status_code=404)


# ── Expirations ───────────────────────────────────────────────────────────────

@router.get("/expirations/{ticker}")
def expirations(ticker: str) -> JSONResponse:
    ticker = ticker.upper()
    eng = make_engine()
    try:
        with eng.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT expiration
                FROM option_chains
                WHERE root = :t
                ORDER BY expiration ASC
            """), {"t": ticker}).fetchall()
        dates = [str(r[0]) for r in rows if r[0]]
        return JSONResponse({"ticker": ticker, "expirations": dates})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Chain ─────────────────────────────────────────────────────────────────────

def _contracts_for_chain(conn, chain_id: int) -> list:
    rows = conn.execute(text("""
        SELECT option_type, strike, bid, ask, last, iv, delta, gamma, theta, vega, volume, open_interest
        FROM option_contracts
        WHERE chain_id = :cid
        ORDER BY strike ASC
    """), {"cid": chain_id}).fetchall()
    return [
        {
            "type": r[0], "strike": r[1], "bid": r[2], "ask": r[3], "last": r[4],
            "mid": round((r[2] + r[3]) / 2, 4) if r[2] and r[3] else None,
            "iv": r[5], "delta": r[6], "gamma": r[7], "theta": r[8], "vega": r[9],
            "volume": r[10], "open_interest": r[11],
        }
        for r in rows
    ]


@router.get("/chain/{ticker}/{expiry}")
def chain(ticker: str, expiry: str) -> JSONResponse:
    ticker = ticker.upper()
    eng = make_engine()
    try:
        with eng.connect() as conn:
            if expiry.lower() == "all":
                # Get all unique expirations (most recent chain per expiry)
                exp_rows = conn.execute(text("""
                    SELECT DISTINCT expiration FROM option_chains
                    WHERE root = :t ORDER BY expiration ASC
                """), {"t": ticker}).fetchall()
                results = []
                for exp_row in exp_rows:
                    exp = exp_row[0]
                    chain_row = conn.execute(text("""
                        SELECT id, root, expiration, underlying_price, quote_time
                        FROM option_chains
                        WHERE root = :t AND expiration = :e
                        ORDER BY quote_time DESC LIMIT 1
                    """), {"t": ticker, "e": exp}).fetchone()
                    if chain_row:
                        contracts = _contracts_for_chain(conn, chain_row[0])
                        results.append({
                            "ticker": chain_row[1],
                            "expiry": str(chain_row[2]),
                            "underlying_price": chain_row[3],
                            "as_of": str(chain_row[4]),
                            "contracts": contracts,
                        })
                return JSONResponse({"ticker": ticker, "chains": results})

            elif expiry.lower() == "front":
                chain_row = conn.execute(text("""
                    SELECT id, root, expiration, underlying_price, quote_time
                    FROM option_chains
                    WHERE root = :t AND expiration >= date('now')
                    ORDER BY expiration ASC, quote_time DESC LIMIT 1
                """), {"t": ticker}).fetchone()
            else:
                chain_row = conn.execute(text("""
                    SELECT id, root, expiration, underlying_price, quote_time
                    FROM option_chains
                    WHERE root = :t AND expiration = :e
                    ORDER BY quote_time DESC LIMIT 1
                """), {"t": ticker, "e": expiry}).fetchone()

            if not chain_row:
                return JSONResponse({"error": f"No chain for {ticker} {expiry}"}, status_code=404)

            contracts = _contracts_for_chain(conn, chain_row[0])

        return JSONResponse({
            "ticker": chain_row[1],
            "expiry": str(chain_row[2]),
            "underlying_price": chain_row[3],
            "as_of": str(chain_row[4]),
            "contracts": contracts,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Subscribe (ad-hoc watchlist) ──────────────────────────────────────────────

@router.post("/subscribe/{ticker}")
def subscribe(ticker: str, hours: int = 24) -> JSONResponse:
    ticker = ticker.upper()
    expires_at = datetime.utcnow() + timedelta(hours=hours)
    eng = make_engine()
    try:
        with eng.connect() as conn:
            # Create table if not exists
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS watchlist_subscriptions (
                    ticker TEXT PRIMARY KEY,
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    source TEXT DEFAULT 'api'
                )
            """))
            conn.execute(text("""
                INSERT INTO watchlist_subscriptions (ticker, expires_at, source)
                VALUES (:t, :e, 'api')
                ON CONFLICT(ticker) DO UPDATE SET expires_at=excluded.expires_at, requested_at=CURRENT_TIMESTAMP
            """), {"t": ticker, "e": expires_at})
            conn.commit()
    except Exception as ex:
        return JSONResponse({"error": str(ex)}, status_code=500)
    return JSONResponse({"subscribed": ticker, "expires_at": expires_at.isoformat(), "hours": hours})


@router.get("/watchlist")
def watchlist() -> JSONResponse:
    eng = make_engine()
    try:
        with eng.connect() as conn:
            # Ensure table exists
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS watchlist_subscriptions (
                    ticker TEXT PRIMARY KEY,
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    source TEXT DEFAULT 'api'
                )
            """))
            rows = conn.execute(text("""
                SELECT ticker, expires_at, source FROM watchlist_subscriptions
                WHERE expires_at > datetime('now')
                ORDER BY expires_at ASC
            """)).fetchall()
        items = [{"ticker": r[0], "expires_at": str(r[1]), "source": r[2]} for r in rows]
        return JSONResponse({"active": items, "count": len(items)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
