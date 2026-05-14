"""IBKR option chain snapshot ingest.

Supports both futures (FUT) and equity ETFs (STK).
Connects to IB Gateway / TWS via ib_async, pulls a single options chain
(root + expiration), and persists it to option_chains + option_contracts.
Also writes the latest snapshot to Redis for real-time access.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from typing import Any


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

from app.analysis.option_pricing import black76, implied_vol
from app.config import ETF_ROOTS, get_settings
from app.models.option_contract import OptionChain, OptionContract, OptionType
from app.storage.repository import upsert_chain

log = logging.getLogger(__name__)


# IBKR exchange + multiplier per futures root.
_IBKR_FUTURES_META: dict[str, dict[str, Any]] = {
    "ZN": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OZN"},
    "ZF": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OZF"},
    "ZB": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OZB"},
    "ZT": {"exchange": "CBOT", "multiplier": 2000.0, "trading_class": "OZT"},
    "TN": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OTN"},
    "UB": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OUB"},
    "ES": {"exchange": "CME",  "multiplier": 50.0,   "trading_class": "ES"},
    "NQ": {"exchange": "CME",  "multiplier": 20.0,   "trading_class": "NQ"},
    "RTY": {"exchange": "CME", "multiplier": 50.0,   "trading_class": "RTY"},
    "CL": {"exchange": "NYMEX","multiplier": 1000.0, "trading_class": "LO"},
    "NG": {"exchange": "NYMEX","multiplier": 10000.0,"trading_class": "ON"},
    "GC": {"exchange": "COMEX","multiplier": 100.0,  "trading_class": "OG"},
    "SI": {"exchange": "COMEX","multiplier": 5000.0, "trading_class": "SO"},
    "HG": {"exchange": "COMEX","multiplier": 25000.0,"trading_class": "HXE"},
    "6E": {"exchange": "CME",  "multiplier": 125000.0,"trading_class": "EUU"},
    "6J": {"exchange": "CME",  "multiplier": 12500000.0,"trading_class": "JPU"},
    "6B": {"exchange": "CME",  "multiplier": 62500.0,"trading_class": "GBU"},
    "6A": {"exchange": "CME",  "multiplier": 100000.0,"trading_class": "ADU"},
    "6C": {"exchange": "CME",  "multiplier": 100000.0,"trading_class": "CAU"},
    "6S": {"exchange": "CME",  "multiplier": 125000.0,"trading_class": "CHU"},
    "VX": {"exchange": "CFE",  "multiplier": 1000.0, "trading_class": "VX"},
}

# ETF metadata — all trade on SMART, multiplier 100
_IBKR_ETF_META: dict[str, dict[str, Any]] = {
    sym: {"exchange": "SMART", "multiplier": 100.0, "currency": "USD"}
    for sym in [
        "EEM", "SPY", "QQQ", "IWM", "FXI", "GLD",
        "TLT", "XLF", "XLE", "XLK", "HYG", "LQD",
    ]
}

# Keep backwards-compat alias
_IBKR_META = _IBKR_FUTURES_META


def _greeks_complete(g: Any) -> bool:
    if g is None:
        return False
    for k in ("impliedVol", "delta", "gamma", "theta", "vega"):
        v = getattr(g, k, None)
        if v is None:
            return False
        if isinstance(v, float) and math.isnan(v):
            return False
    return True


def _wait_for_ticker_price(ib, ticker, timeout: float = 10.0) -> None:
    import time as _time
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        ib.sleep(0.5)
        for v in (ticker.marketPrice(), ticker.last, ticker.close,
                  ticker.bid, ticker.ask):
            if _safe_price(v) is not None:
                return
    return


def ingest(*, root: str, expiration: str | None = None,
           strikes: list[float] | None = None,
           num_strikes: int = 41, **_kwargs) -> int:
    """Pull a chain for `root`. Supports both futures and ETFs.

    Returns 1 on success or 0 on skip/failure.
    """
    s = get_settings()
    if not s.ibkr_enabled:
        log.info("IBKR_ENABLED=false; skipping IBKR ingest for %s", root)
        return 0

    root_upper = root.upper()
    if root_upper in ETF_ROOTS:
        chain = _fetch_etf_chain(s, root_upper, expiration, strikes, num_strikes)
    else:
        meta = _IBKR_FUTURES_META.get(root_upper)
        if meta is None:
            log.warning("no IBKR metadata for %s", root_upper)
            return 0
        chain = _fetch_chain(s, root_upper, meta, expiration, strikes, num_strikes)

    if chain is None:
        return 0
    upsert_chain(chain, vendor="ibkr")
    _write_to_redis(chain)
    return 1


def _write_to_redis(chain: OptionChain) -> None:
    """Write chain snapshot to Redis as a hot cache (TTL 10 min)."""
    try:
        import json, os, redis
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(url, decode_responses=True)
        key = f"chain:{chain.root}:{chain.expiration.isoformat()}"
        payload = {
            "root": chain.root,
            "underlying_symbol": chain.underlying_symbol,
            "underlying_price": chain.underlying_price,
            "expiration": chain.expiration.isoformat(),
            "quote_time": chain.quote_time.isoformat(),
            "multiplier": chain.multiplier,
            "contracts": [
                {
                    "type": c.option_type.value,
                    "strike": c.strike,
                    "bid": c.bid,
                    "ask": c.ask,
                    "iv": c.iv,
                    "delta": c.delta,
                    "gamma": c.gamma,
                    "theta": c.theta,
                    "vega": c.vega,
                    "volume": c.volume,
                }
                for c in chain.contracts
            ],
        }
        r.setex(key, 600, json.dumps(payload))
        # Also update latest-quote hash for the root
        r.hset(f"quote:{chain.root}", mapping={
            "price": chain.underlying_price,
            "updated_at": chain.quote_time.isoformat(),
        })
        r.expire(f"quote:{chain.root}", 600)
        log.info("[%s] wrote chain to Redis key=%s (%d contracts)",
                 chain.root, key, len(chain.contracts))
    except Exception as e:
        log.warning("[%s] Redis write failed (non-fatal): %s", chain.root, e)


def _fetch_etf_chain(s, root: str, expiration: str | None,
                     strikes: list[float] | None, num_strikes: int) -> OptionChain | None:
    """Pull options chain for an equity ETF (STK secType)."""
    from ib_async import IB, Stock, Option

    meta = _IBKR_ETF_META.get(root)
    if meta is None:
        log.warning("[%s] no ETF metadata", root)
        return None

    log.info("[%s] connecting to IB Gateway %s:%d (ETF mode)", root, s.ibkr_host, s.ibkr_port)
    ib = IB()
    try:
        ib.connect(s.ibkr_host, s.ibkr_port, clientId=s.ibkr_client_id + 1,
                   readonly=True, timeout=15)

        # Qualify underlying stock
        underlying = Stock(root, meta["exchange"], meta["currency"])
        ib.qualifyContracts(underlying)
        ticker = ib.reqMktData(underlying, "", snapshot=True)
        _wait_for_ticker_price(ib, ticker, timeout=10.0)

        underlying_price = (
            _safe_price(ticker.marketPrice())
            or _safe_price(ticker.last)
            or _safe_price(ticker.close)
        )
        if underlying_price is None:
            log.warning("[%s] no underlying price", root)
            return None
        log.info("[%s] underlying price: %s", root, underlying_price)

        # Get option chain params
        all_params = ib.reqSecDefOptParams(root, "", "STK", underlying.conId)
        if not all_params:
            log.warning("[%s] no option params returned", root)
            return None

        # Pick expiration
        if expiration is not None:
            expiry_yyyymmdd = expiration.replace("-", "")
        else:
            from datetime import timedelta as _td
            min_dt = (datetime.now(tz=timezone.utc).date() + _td(days=7))
            min_str = min_dt.strftime("%Y%m%d")
            today_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
            all_expiries = sorted({e for p in all_params for e in p.expirations})
            future_expiries = [e for e in all_expiries if e >= min_str]
            if not future_expiries:
                future_expiries = [e for e in all_expiries if e >= today_str]
            if not future_expiries:
                log.warning("[%s] no future expirations", root)
                return None
            expiry_yyyymmdd = future_expiries[0]
            log.info("[%s] auto-selected expiry %s", root, expiry_yyyymmdd)

        expiration_d = date(int(expiry_yyyymmdd[:4]),
                            int(expiry_yyyymmdd[4:6]),
                            int(expiry_yyyymmdd[6:8]))

        # Select strikes
        if strikes is None:
            all_strikes = sorted({k for p in all_params for k in p.strikes})
            atm = min(all_strikes, key=lambda k: abs(k - underlying_price))
            atm_idx = all_strikes.index(atm)
            half = num_strikes // 2
            chosen = all_strikes[max(0, atm_idx - half): atm_idx + half + 1]
        else:
            chosen = sorted(set(strikes))

        # Build and qualify option contracts
        option_contracts = []
        for k in chosen:
            for right in ("C", "P"):
                opt = Option(
                    symbol=root,
                    lastTradeDateOrContractMonth=expiry_yyyymmdd,
                    strike=k,
                    right=right,
                    exchange="SMART",
                    currency="USD",
                )
                option_contracts.append(opt)

        ib.qualifyContracts(*option_contracts)
        qualified = [c for c in option_contracts if getattr(c, "conId", 0)]
        log.info("[%s] %d/%d option contracts qualified", root,
                 len(qualified), len(option_contracts))

        tickers = [ib.reqMktData(c, "106", snapshot=False, regulatorySnapshot=False)
                   for c in qualified]
        if tickers:
            _wait_for_ticker_price(ib, tickers[0], timeout=10.0)
        ib.sleep(2.0)

        now_utc = datetime.now(tz=timezone.utc)
        today = now_utc.date()
        T_years = max((expiration_d - today).days / 365.25, 1.0 / 365.25)
        contracts = []

        for contract, t in zip(qualified, tickers):
            bid = _safe_price(t.bid)
            ask = _safe_price(t.ask)
            last = _safe_price(t.last)
            close = _safe_price(t.close)

            if bid is not None and ask is not None:
                option_price = (bid + ask) / 2.0
                final_bid, final_ask = bid, ask
            elif last is not None:
                option_price = last
                final_bid, final_ask = last, last
            elif close is not None:
                option_price = close
                final_bid, final_ask = close, close
            else:
                continue

            ot = OptionType(contract.right)
            greeks = t.modelGreeks
            if _greeks_complete(greeks):
                iv = float(greeks.impliedVol)
                delta = float(greeks.delta)
                gamma = float(greeks.gamma)
                theta = float(greeks.theta)
                vega = float(greeks.vega)
            else:
                try:
                    iv = implied_vol(F=float(underlying_price), K=float(contract.strike),
                                     market_price=option_price, T=T_years, r=0.05,
                                     option_type=ot)
                    b76 = black76(F=float(underlying_price), K=float(contract.strike),
                                  sigma=iv, T=T_years, r=0.05, option_type=ot)
                    delta = b76.delta
                    gamma = b76.gamma
                    theta = b76.theta / 365.0
                    vega = b76.vega / 100.0
                except Exception:
                    continue

            try:
                contracts.append(OptionContract(
                    root=root,
                    underlying_symbol=root,
                    underlying_price=float(underlying_price),
                    option_type=ot,
                    strike=float(contract.strike),
                    expiration=expiration_d,
                    multiplier=meta["multiplier"],
                    bid=final_bid, ask=final_ask, last=last,
                    iv=iv, delta=delta, gamma=gamma, theta=theta, vega=vega,
                    volume=int(t.volume) if t.volume else 0,
                    open_interest=0,
                    quote_time=now_utc,
                ))
            except Exception:
                continue

        if not contracts:
            log.warning("[%s] no usable contracts", root)
            return None

        return OptionChain(
            root=root,
            underlying_symbol=root,
            underlying_price=float(underlying_price),
            expiration=expiration_d,
            quote_time=now_utc,
            contracts=contracts,
            multiplier=meta["multiplier"],
        )
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


def _fetch_chain(s, root: str, meta: dict, expiration: str | None,
                 strikes: list[float] | None, num_strikes: int) -> OptionChain | None:
    from ib_async import IB, Future, FuturesOption

    log.info("[%s] connecting to IB Gateway %s:%d (clientId=%d)",
             root, s.ibkr_host, s.ibkr_port, s.ibkr_client_id)
    ib = IB()
    try:
        ib.connect(s.ibkr_host, s.ibkr_port, clientId=s.ibkr_client_id,
                   readonly=True, timeout=15)

        underlying = Future(symbol=root, exchange=meta["exchange"], includeExpired=False)
        details = ib.reqContractDetails(underlying)
        if not details:
            log.warning("[%s] no IBKR future details", root)
            return None

        future_contract = sorted(
            details, key=lambda d: d.contract.lastTradeDateOrContractMonth
        )[0].contract
        ib.qualifyContracts(future_contract)
        ticker = ib.reqMktData(future_contract, "", snapshot=True)
        _wait_for_ticker_price(ib, ticker, timeout=10.0)
        underlying_price = (
            _safe_price(ticker.marketPrice())
            or _safe_price(ticker.last)
            or _safe_price(ticker.close)
        )
        if underlying_price is None:
            log.warning("[%s] no underlying mark", root)
            return None
        underlying_symbol = future_contract.localSymbol or f"{root}{future_contract.lastTradeDateOrContractMonth}"

        all_params = ib.reqSecDefOptParams(
            future_contract.symbol, meta["exchange"], "FUT", future_contract.conId
        )
        if not all_params:
            log.warning("[%s] no option params returned", root)
            return None

        params = [p for p in all_params if p.tradingClass == meta["trading_class"]]
        if not params:
            log.warning("[%s] no secdef params matched tradingClass=%s", root, meta["trading_class"])
            return None

        if expiration is not None:
            expiry_yyyymmdd = expiration.replace("-", "")
        else:
            from datetime import timedelta as _td
            min_dt = (datetime.now(tz=timezone.utc).date() + _td(days=7))
            min_str = min_dt.strftime("%Y%m%d")
            today_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
            all_expiries = sorted({e for p in params for e in p.expirations})
            future_expiries = [e for e in all_expiries if e >= min_str]
            if not future_expiries:
                future_expiries = [e for e in all_expiries if e >= today_str]
            if not future_expiries:
                log.warning("[%s] no future expirations", root)
                return None
            expiry_yyyymmdd = future_expiries[0]

        expiration_d = date(int(expiry_yyyymmdd[:4]),
                             int(expiry_yyyymmdd[4:6]),
                             int(expiry_yyyymmdd[6:8]))

        if strikes is None:
            all_strikes = sorted({k for p in params for k in p.strikes})
            atm = min(all_strikes, key=lambda k: abs(k - underlying_price))
            atm_idx = all_strikes.index(atm)
            half = num_strikes // 2
            chosen = all_strikes[max(0, atm_idx - half): atm_idx + half + 1]
        else:
            chosen = sorted(set(strikes))

        option_contracts: list[Any] = []
        for k in chosen:
            for right in ("C", "P"):
                opt = FuturesOption(
                    symbol=root,
                    lastTradeDateOrContractMonth=expiry_yyyymmdd,
                    strike=k, right=right,
                    exchange=meta["exchange"],
                    multiplier=str(int(meta["multiplier"])),
                    tradingClass=meta["trading_class"],
                )
                option_contracts.append(opt)

        ib.qualifyContracts(*option_contracts)
        tickers = [ib.reqMktData(c, "106", snapshot=False, regulatorySnapshot=False)
                   for c in option_contracts]
        if tickers:
            _wait_for_ticker_price(ib, tickers[0], timeout=10.0)
        ib.sleep(2.0)

        contracts: list[OptionContract] = []
        now_utc = datetime.now(tz=timezone.utc)
        today = now_utc.date()
        T_years = max((expiration_d - today).days / 365.25, 1.0 / 365.25)

        for contract, t in zip(option_contracts, tickers):
            bid = _safe_price(t.bid)
            ask = _safe_price(t.ask)
            last = _safe_price(t.last)
            close = _safe_price(t.close)

            if bid is not None and ask is not None:
                option_price = (bid + ask) / 2.0
                final_bid, final_ask = bid, ask
            elif last is not None:
                option_price = last
                final_bid, final_ask = last, last
            elif close is not None:
                option_price = close
                final_bid, final_ask = close, close
            else:
                continue

            ot = OptionType(contract.right)
            greeks = t.modelGreeks
            if _greeks_complete(greeks):
                iv = float(greeks.impliedVol)
                delta = float(greeks.delta)
                gamma = float(greeks.gamma)
                theta = float(greeks.theta)
                vega = float(greeks.vega)
            else:
                try:
                    iv = implied_vol(F=float(underlying_price), K=float(contract.strike),
                                     market_price=option_price, T=T_years, r=0.05,
                                     option_type=ot)
                    b76 = black76(F=float(underlying_price), K=float(contract.strike),
                                  sigma=iv, T=T_years, r=0.05, option_type=ot)
                    delta = b76.delta
                    gamma = b76.gamma
                    theta = b76.theta / 365.0
                    vega = b76.vega / 100.0
                except Exception:
                    continue

            try:
                contracts.append(OptionContract(
                    root=root,
                    underlying_symbol=underlying_symbol,
                    underlying_price=float(underlying_price),
                    option_type=ot,
                    strike=float(contract.strike),
                    expiration=expiration_d,
                    multiplier=meta["multiplier"],
                    bid=final_bid, ask=final_ask, last=last,
                    iv=iv, delta=delta, gamma=gamma, theta=theta, vega=vega,
                    volume=int(t.volume) if t.volume else 0,
                    open_interest=0,
                    quote_time=now_utc,
                ))
            except Exception:
                continue

        if not contracts:
            log.warning("[%s] no usable contracts", root)
            return None

        return OptionChain(
            root=root,
            underlying_symbol=underlying_symbol,
            underlying_price=float(underlying_price),
            expiration=expiration_d,
            quote_time=now_utc,
            contracts=contracts,
            multiplier=meta["multiplier"],
        )
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass
