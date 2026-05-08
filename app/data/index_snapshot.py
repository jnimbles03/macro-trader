"""Index/macro ticker snapshots via IBKR Gateway.

Pulls last + prior-close for a fixed list of ETFs, futures, and cash indices.
Module-level TTL cache so the FastAPI endpoint doesn't hammer IB on every
request — refresh window is intentionally short (~30s) to feel live without
swamping the gateway.

Design:
- One IB connection per refresh, snapshot=True so we don't subscribe to
  streaming ticks.
- Graceful failure: if the gateway isn't reachable, return the last cached
  payload (with `stale=True`) instead of erroring; if individual symbols
  don't quote, return them with `last=None`.
"""

from __future__ import annotations

import logging
import math
import socket
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)


def _safe_price(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or f <= 0:
        return None
    return f


@dataclass
class IndexQuote:
    label: str
    kind: str            # "stock" | "future" | "index"
    last: float | None
    prev_close: float | None
    change: float | None
    change_pct: float | None
    currency: str | None
    change_2d_pct: float | None = None   # cumulative return over the last 2 trading days
    error: str | None = None


# (display_label, instrument_kind, ib_async_args)
# Stocks resolve to SMART; futures need front-month resolution; indices use
# the cash index contract type.
_INSTRUMENTS: list[tuple[str, str, dict[str, Any]]] = [
    ("SPY", "stock", {"symbol": "SPY", "exchange": "SMART", "currency": "USD"}),
    ("DIA", "stock", {"symbol": "DIA", "exchange": "SMART", "currency": "USD"}),
    ("QQQ", "stock", {"symbol": "QQQ", "exchange": "SMART", "currency": "USD"}),
    ("BND", "stock", {"symbol": "BND", "exchange": "SMART", "currency": "USD"}),
    ("HYG", "stock", {"symbol": "HYG", "exchange": "SMART", "currency": "USD"}),
    ("SHY", "stock", {"symbol": "SHY", "exchange": "SMART", "currency": "USD"}),
    ("TLT", "stock", {"symbol": "TLT", "exchange": "SMART", "currency": "USD"}),
    ("MUB", "stock", {"symbol": "MUB", "exchange": "SMART", "currency": "USD"}),
    ("EEM", "stock", {"symbol": "EEM", "exchange": "SMART", "currency": "USD"}),
    ("FXI", "stock", {"symbol": "FXI", "exchange": "SMART", "currency": "USD"}),
    ("ZN",  "future", {"symbol": "ZN", "exchange": "CBOT"}),
    ("ZB",  "future", {"symbol": "ZB", "exchange": "CBOT"}),
    ("VIX", "index",  {"symbol": "VIX", "exchange": "CBOE", "currency": "USD"}),
    ("FTSE", "index", {"symbol": "UKX", "exchange": "LIFFE", "currency": "GBP"}),
    ("DAX", "index",  {"symbol": "DAX", "exchange": "EUREX", "currency": "EUR"}),
]


_TTL_SECONDS = 30.0
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"as_of": 0.0, "data": None}


def get_snapshot() -> dict[str, Any]:
    """Return cached snapshot if fresh, otherwise refresh.

    The lock serializes refreshes so multiple concurrent requests don't all
    open IBKR connections at once.
    """
    now = time.time()
    with _cache_lock:
        if _cache["data"] is not None and (now - _cache["as_of"]) < _TTL_SECONDS:
            payload = dict(_cache["data"])
            payload["age_seconds"] = round(now - _cache["as_of"], 1)
            return payload
        try:
            quotes = _fetch_all()
            _cache["data"] = {
                "quotes": [asdict(q) for q in quotes],
                "fetched_at": now,
                "stale": False,
                "gateway_error": None,
            }
            _cache["as_of"] = now
        except Exception as e:
            log.warning("index snapshot fetch failed: %s", e)
            if _cache["data"] is not None:
                stale = dict(_cache["data"])
                stale["stale"] = True
                stale["gateway_error"] = str(e)
                stale["age_seconds"] = round(now - _cache["as_of"], 1)
                return stale
            return {
                "quotes": [],
                "fetched_at": now,
                "stale": True,
                "gateway_error": str(e),
                "age_seconds": 0.0,
            }
        payload = dict(_cache["data"])
        payload["age_seconds"] = 0.0
        return payload


def _probe_gateway(host: str, port: int, timeout: float = 1.0) -> bool:
    """Cheap TCP probe so we can fail fast when the gateway isn't running."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def _fetch_all() -> list[IndexQuote]:
    s = get_settings()
    # Snapshot is read-only and idempotent — auto-detect rather than gate on
    # IBKR_ENABLED (which the chain ingest still respects, since that writes
    # to the warehouse). If the gateway is reachable, use it.
    if not _probe_gateway(s.ibkr_host, s.ibkr_port):
        raise RuntimeError(
            f"IB Gateway not reachable at {s.ibkr_host}:{s.ibkr_port}"
        )

    from ib_async import IB, Future, Index, Stock

    ib = IB()
    ib.connect(s.ibkr_host, s.ibkr_port, clientId=s.ibkr_client_id + 1,
               readonly=True, timeout=8)
    try:
        # Build contracts; resolve front-month for futures.
        contracts: list[tuple[str, str, str | None, Any]] = []
        for label, kind, args in _INSTRUMENTS:
            try:
                if kind == "stock":
                    c = Stock(**args)
                elif kind == "index":
                    c = Index(**args)
                elif kind == "future":
                    underlying = Future(symbol=args["symbol"], exchange=args["exchange"],
                                        includeExpired=False)
                    details = ib.reqContractDetails(underlying)
                    if not details:
                        contracts.append((label, kind, None, None))
                        continue
                    c = sorted(details,
                               key=lambda d: d.contract.lastTradeDateOrContractMonth)[0].contract
                else:
                    continue
                contracts.append((label, kind, args.get("currency"), c))
            except Exception as e:
                log.debug("contract resolve failed for %s: %s", label, e)
                contracts.append((label, kind, args.get("currency"), None))

        # Qualify in one batch where possible.
        to_qualify = [c for _, _, _, c in contracts if c is not None]
        if to_qualify:
            try:
                ib.qualifyContracts(*to_qualify)
            except Exception as e:
                log.debug("qualifyContracts batch warning: %s", e)

        # Request snapshots.
        tickers: dict[str, Any] = {}
        for label, _kind, _ccy, c in contracts:
            if c is None or not getattr(c, "conId", 0):
                tickers[label] = None
                continue
            try:
                tickers[label] = ib.reqMktData(c, "", snapshot=True, regulatorySnapshot=False)
            except Exception as e:
                log.debug("reqMktData failed for %s: %s", label, e)
                tickers[label] = None

        # Snapshots take up to ~11s per IBKR; poll every 0.5s and bail when
        # everything we asked for has both a last and a close.
        deadline = time.time() + 12.0
        while time.time() < deadline:
            ib.sleep(0.5)
            ready = 0
            asked = 0
            for label, t in tickers.items():
                if t is None:
                    continue
                asked += 1
                if _safe_price(t.last) is not None and _safe_price(t.close) is not None:
                    ready += 1
                elif _safe_price(t.marketPrice()) is not None and _safe_price(t.close) is not None:
                    ready += 1
            if asked > 0 and ready >= asked:
                break

        # Pull 3 trading days of dailies per contract for the 2d return.
        # Sequential because reqHistoricalData is throttled per contract; the
        # 30s panel cache means we only pay this once per refresh cycle.
        history_2d: dict[str, float | None] = {}
        for label, _kind, _ccy, c in contracts:
            history_2d[label] = None
            if c is None or not getattr(c, "conId", 0):
                continue
            try:
                bars = ib.reqHistoricalData(
                    c, endDateTime="", durationStr="3 D",
                    barSizeSetting="1 day", whatToShow="TRADES",
                    useRTH=True, formatDate=2, keepUpToDate=False,
                )
                closes = [b.close for b in bars if getattr(b, "close", None)]
                if len(closes) >= 3:
                    two_days_ago = closes[-3]
                    today = closes[-1]
                    if two_days_ago and today:
                        history_2d[label] = (today / two_days_ago) - 1.0
            except Exception as e:
                log.debug("reqHistoricalData failed for %s: %s", label, e)

        out: list[IndexQuote] = []
        for label, kind, ccy, c in contracts:
            t = tickers.get(label)
            if c is None or t is None:
                out.append(IndexQuote(label=label, kind=kind, last=None, prev_close=None,
                                      change=None, change_pct=None, currency=ccy,
                                      change_2d_pct=None, error="not resolved"))
                continue
            last = (
                _safe_price(t.last)
                or _safe_price(t.marketPrice())
                or _safe_price(t.close)
            )
            prev = _safe_price(t.close)
            change = (last - prev) if (last is not None and prev is not None and last != prev) else None
            change_pct = (change / prev) if (change is not None and prev) else None
            out.append(IndexQuote(label=label, kind=kind, last=last, prev_close=prev,
                                  change=change, change_pct=change_pct, currency=ccy,
                                  change_2d_pct=history_2d.get(label)))
        return out
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


def get_mock_snapshot() -> dict[str, Any]:
    """Synthetic data so the UI is functional without a live gateway."""
    # (label, kind, last, today_pct, prior_pct)
    seed = [
        ("SPY", "stock", 567.42, 0.0042, -0.0028),
        ("DIA", "stock", 412.18, 0.0028, -0.0014),
        ("QQQ", "stock", 489.05, 0.0061, -0.0042),
        ("BND", "stock", 73.21, -0.0015, -0.0023),
        ("HYG", "stock", 79.84, 0.0008, -0.0019),
        ("SHY", "stock", 82.30, 0.0002, 0.0001),
        ("TLT", "stock", 92.55, -0.0073, -0.0094),
        ("MUB", "stock", 107.12, -0.0011, -0.0022),
        ("EEM", "stock", 43.91, -0.0044, -0.0061),
        ("FXI", "stock", 30.07, -0.0102, -0.0145),
        ("ZN",  "future", 110.85, -0.0019, -0.0034),
        ("ZB",  "future", 116.40, -0.0036, -0.0058),
        ("VIX", "index", 14.32, 0.0218, 0.0312),
        ("FTSE", "index", 8245.10, 0.0015, -0.0008),
        ("DAX", "index", 18540.60, -0.0034, -0.0021),
    ]
    quotes = []
    for label, kind, last, pct, prior_pct in seed:
        prev = last / (1 + pct)
        change = last - prev
        # 2d cumulative compounding (1+today)*(1+prior) - 1
        change_2d = (1 + pct) * (1 + prior_pct) - 1
        ccy = {"FTSE": "GBP", "DAX": "EUR"}.get(label, "USD")
        quotes.append(asdict(IndexQuote(
            label=label, kind=kind, last=last, prev_close=prev,
            change=change, change_pct=pct, currency=ccy,
            change_2d_pct=change_2d,
        )))
    return {
        "quotes": quotes,
        "fetched_at": time.time(),
        "stale": False,
        "gateway_error": None,
        "age_seconds": 0.0,
        "mock": True,
    }
