"""IBKR market data diagnostic.

Connects to IB Gateway, probes the underlying future + a near-ATM option for
each root, and reports what data flowed:

  - Live (real-time bid/ask + IBKR-computed Greeks)
  - Delayed (15-min stale bid/ask, Greeks via Black-76 fallback)
  - Close-only (yesterday's close, no live ticks)
  - None (no data at all — likely missing subscription)

Use this to see exactly what your IBKR market data subscriptions cover for
the trade universe (ZN/ES/CL/GC) without leaving the terminal.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.ingest.ibkr_chain import _IBKR_META, _safe_price, _wait_for_ticker_price

log = logging.getLogger(__name__)


@dataclass
class RootStatus:
    root: str
    underlying_status: str           # "live" | "delayed" | "close_only" | "none"
    underlying_price: float | None
    options_status: str               # "live_with_greeks" | "delayed_no_greeks" | "close_only" | "none"
    sample_strike: float | None
    sample_bid: float | None
    sample_ask: float | None
    sample_close: float | None
    notes: str = ""


def probe(roots: list[str]) -> list[RootStatus]:
    s = get_settings()
    if not s.ibkr_enabled:
        return [RootStatus(r, "skipped", None, "skipped", None, None, None, None,
                            notes="IBKR_ENABLED=false in .env") for r in roots]

    from ib_async import IB, Future, FuturesOption

    ib = IB()
    results: list[RootStatus] = []
    try:
        ib.connect(s.ibkr_host, s.ibkr_port, clientId=s.ibkr_client_id,
                   readonly=True, timeout=15)
        log.info("connected to %s:%d", s.ibkr_host, s.ibkr_port)

        for root in roots:
            results.append(_probe_root(ib, root))
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass
    return results


def _probe_root(ib: Any, root: str) -> RootStatus:
    meta = _IBKR_META.get(root.upper())
    if meta is None:
        return RootStatus(root, "none", None, "none", None, None, None, None,
                          notes=f"no metadata for root {root}")

    from ib_async import Future, FuturesOption

    underlying = Future(symbol=root, exchange=meta["exchange"], includeExpired=False)
    details = ib.reqContractDetails(underlying)
    if not details:
        return RootStatus(root, "none", None, "none", None, None, None, None,
                          notes="no future contract details — likely no subscription "
                                f"for {meta['exchange']}")

    future_contract = sorted(
        details, key=lambda d: d.contract.lastTradeDateOrContractMonth
    )[0].contract
    ib.qualifyContracts(future_contract)

    # Probe underlying
    fut_ticker = ib.reqMktData(future_contract, "", snapshot=True)
    _wait_for_ticker_price(ib, fut_ticker, timeout=8.0)
    fut_bid = _safe_price(fut_ticker.bid)
    fut_ask = _safe_price(fut_ticker.ask)
    fut_last = _safe_price(fut_ticker.last)
    fut_close = _safe_price(fut_ticker.close)

    if fut_bid is not None and fut_ask is not None:
        underlying_status = "live"
        underlying_price = (fut_bid + fut_ask) / 2.0
    elif fut_last is not None:
        underlying_status = "delayed"
        underlying_price = fut_last
    elif fut_close is not None:
        underlying_status = "close_only"
        underlying_price = fut_close
    else:
        return RootStatus(root, "none", None, "none", None, None, None, None,
                          notes="no underlying mark at all")

    # Probe options chain — use the front OZN/OES/etc tradingClass entry
    params = ib.reqSecDefOptParams(
        future_contract.symbol, meta["exchange"], "FUT", future_contract.conId
    )
    matching = [p for p in params if p.tradingClass == meta["trading_class"]]
    if not matching:
        return RootStatus(root, underlying_status, underlying_price,
                          "none", None, None, None, None,
                          notes=f"no {meta['trading_class']} secdef params; "
                                "options likely not exposed for this root")

    today_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    expiries = sorted({e for p in matching for e in p.expirations})
    expiries = [e for e in expiries if e >= today_str]
    if not expiries:
        return RootStatus(root, underlying_status, underlying_price,
                          "none", None, None, None, None, notes="no future expirations")
    expiry = expiries[0]

    strikes = sorted({k for p in matching for k in p.strikes})
    if not strikes:
        return RootStatus(root, underlying_status, underlying_price,
                          "none", None, None, None, None, notes="no strikes")
    atm_strike = min(strikes, key=lambda k: abs(k - underlying_price))

    opt = FuturesOption(
        symbol=root, lastTradeDateOrContractMonth=expiry,
        strike=atm_strike, right="C",
        exchange=meta["exchange"],
        multiplier=str(int(meta["multiplier"])),
        tradingClass=meta["trading_class"],
    )
    try:
        ib.qualifyContracts(opt)
    except Exception as e:
        return RootStatus(root, underlying_status, underlying_price,
                          "none", atm_strike, None, None, None,
                          notes=f"option qualify failed: {e}")

    opt_ticker = ib.reqMktData(opt, "106", snapshot=False, regulatorySnapshot=False)
    ib.sleep(2.5)
    opt_bid = _safe_price(opt_ticker.bid)
    opt_ask = _safe_price(opt_ticker.ask)
    opt_close = _safe_price(opt_ticker.close)
    greeks = opt_ticker.modelGreeks
    has_greeks = greeks is not None and getattr(greeks, "delta", None) is not None \
        and not (isinstance(greeks.delta, float) and math.isnan(greeks.delta))

    if opt_bid is not None and opt_ask is not None and has_greeks:
        options_status = "live_with_greeks"
    elif opt_bid is not None and opt_ask is not None:
        options_status = "delayed_no_greeks"
    elif opt_close is not None:
        options_status = "close_only"
    else:
        options_status = "none"

    return RootStatus(
        root=root,
        underlying_status=underlying_status,
        underlying_price=underlying_price,
        options_status=options_status,
        sample_strike=atm_strike,
        sample_bid=opt_bid,
        sample_ask=opt_ask,
        sample_close=opt_close,
    )


def explain(status: list[RootStatus]) -> str:
    lines = []
    for r in status:
        lines.append(f"\n[{r.root}]")
        lines.append(f"  Underlying: {r.underlying_status}"
                     + (f" @ {r.underlying_price:.4f}" if r.underlying_price else ""))
        if r.sample_strike is not None:
            lines.append(f"  Options    : {r.options_status} "
                         f"(probed {r.sample_strike}C "
                         f"bid={r.sample_bid} ask={r.sample_ask} close={r.sample_close})")
        else:
            lines.append(f"  Options    : {r.options_status}")
        if r.notes:
            lines.append(f"  Note       : {r.notes}")
    lines.append("\nLegend:")
    lines.append("  live              — real-time NBBO (you have the subscription)")
    lines.append("  live_with_greeks  — real-time + IBKR-computed IV/Greeks")
    lines.append("  delayed           — bid/ask present, ~15 min stale")
    lines.append("  delayed_no_greeks — bid/ask present, but Greeks via our Black-76 fallback")
    lines.append("  close_only        — only previous session close, no live ticks at all")
    lines.append("  none              — no data; subscription likely missing for this exchange")
    return "\n".join(lines)
