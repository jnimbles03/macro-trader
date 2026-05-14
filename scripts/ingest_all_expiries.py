"""
One-shot script: ingest ALL available expiries for a list of ETF tickers.
Connects once per ticker, discovers all expirations, then loops them.

Usage:
    python scripts/ingest_all_expiries.py [EEM SPY QQQ ...]
"""
from __future__ import annotations

import logging
import sys
import os
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("ingest_all_expiries")


def get_all_expirations(root: str) -> list[str]:
    """Connect to IB once and return all available option expirations for root."""
    from ib_async import IB, Stock
    from app.config import get_settings

    s = get_settings()
    root_upper = root.upper()
    ib = IB()
    try:
        ib.connect(s.ibkr_host, s.ibkr_port, clientId=s.ibkr_client_id + 2, readonly=True, timeout=15)
        underlying = Stock(root_upper, "SMART", "USD")
        ib.qualifyContracts(underlying)

        all_params = ib.reqSecDefOptParams(root_upper, "", "STK", underlying.conId)
        if not all_params:
            log.warning("[%s] no option params returned", root_upper)
            return []

        today_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        all_expiries = sorted({e for p in all_params for e in p.expirations if e >= today_str})
        log.info("[%s] found %d expirations", root_upper, len(all_expiries))
        return all_expiries
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


def run(tickers: list[str]) -> None:
    from app.ingest.ibkr_chain import ingest

    for ticker in tickers:
        ticker = ticker.upper()
        log.info("=== %s: discovering expirations ===", ticker)
        expiries = get_all_expirations(ticker)
        if not expiries:
            log.warning("[%s] no expirations found, skipping", ticker)
            continue

        log.info("[%s] ingesting %d expirations: %s ... %s",
                 ticker, len(expiries), expiries[0], expiries[-1])

        ok = 0
        fail = 0
        for expiry in expiries:
            expiry_fmt = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:8]}"
            log.info("[%s] pulling expiry %s", ticker, expiry_fmt)
            try:
                result = ingest(root=ticker, expiration=expiry_fmt, num_strikes=41)
                if result:
                    ok += 1
                    log.info("[%s] %s OK", ticker, expiry_fmt)
                else:
                    fail += 1
                    log.warning("[%s] %s returned 0 (skip/fail)", ticker, expiry_fmt)
            except Exception as e:
                fail += 1
                log.error("[%s] %s ERROR: %s", ticker, expiry_fmt, e)

        log.info("=== %s done: %d OK, %d failed ===", ticker, ok, fail)


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["EEM"]
    run(tickers)
