"""IBKR option chain snapshot ingest.

Connects to IB Gateway / TWS via ib_async, pulls a single options-on-futures
chain (root + expiration), and persists it to `option_chains` +
`option_contracts`. No backfill — chains are point-in-time data.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from typing import Any


def _safe_price(v: Any) -> float | None:
    """IBKR returns NaN/None/-1 for unsubscribed quotes. Treat all as missing."""
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
from app.config import get_settings
from app.models.option_contract import OptionChain, OptionContract, OptionType
from app.storage.repository import upsert_chain


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

log = logging.getLogger(__name__)


# IBKR exchange + multiplier per root.
_IBKR_META: dict[str, dict[str, Any]] = {
    "ZN": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OZN"},
    "ZF": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OZF"},
    "ZB": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OZB"},
    "ZT": {"exchange": "CBOT", "multiplier": 2000.0, "trading_class": "OZT"},
    "TN": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OTN"},
    "UB": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OUB"},
    "ES": {"exchange": "CME", "multiplier": 50.0, "trading_class": "ES"},
    "NQ": {"exchange": "CME", "multiplier": 20.0, "trading_class": "NQ"},
    "RTY": {"exchange": "CME", "multiplier": 50.0, "trading_class": "RTY"},
    "CL": {"exchange": "NYMEX", "multiplier": 1000.0, "trading_class": "LO"},
    "NG": {"exchange": "NYMEX", "multiplier": 10000.0, "trading_class": "ON"},
    "GC": {"exchange": "COMEX", "multiplier": 100.0, "trading_class": "OG"},
    "SI": {"exchange": "COMEX", "multiplier": 5000.0, "trading_class": "SO"},
    "HG": {"exchange": "COMEX", "multiplier": 25000.0, "trading_class": "HXE"},
    "6E": {"exchange": "CME", "multiplier": 125000.0, "trading_class": "EUU"},
    "6J": {"exchange": "CME", "multiplier": 12500000.0, "trading_class": "JPU"},
    "6B": {"exchange": "CME", "multiplier": 62500.0, "trading_class": "GBU"},
    "6A": {"exchange": "CME", "multiplier": 100000.0, "trading_class": "ADU"},
    "6C": {"exchange": "CME", "multiplier": 100000.0, "trading_class": "CAU"},
    "6S": {"exchange": "CME", "multiplier": 125000.0, "trading_class": "CHU"},
    "VX": {"exchange": "CFE", "multiplier": 1000.0, "trading_class": "VX"},
}


def ingest(*, root: str, expiration: str | None = None,
           strikes: list[float] | None = None,
           num_strikes: int = 11, **_kwargs) -> int:
    """Pull a chain for `root` at the front-month expiration (or `expiration`).

    `strikes` overrides the auto-selection. `num_strikes` controls how many
    near-the-money strikes to pull when auto-selecting (calls + puts each).
    Returns 1 on success (one chain row written) or 0 on skip/failure.
    """
    s = get_settings()
    if not s.ibkr_enabled:
        log.info("IBKR_ENABLED=false; skipping IBKR ingest for %s", root)
        return 0

    meta = _IBKR_META.get(root.upper())
    if meta is None:
        log.warning("no IBKR metadata for %s", root)
        return 0

    chain = _fetch_chain(s, root.upper(), meta, expiration, strikes, num_strikes)
    if chain is None:
        return 0
    upsert_chain(chain, vendor="ibkr")
    return 1


def _fetch_chain(s, root: str, meta: dict, expiration: str | None,
                 strikes: list[float] | None, num_strikes: int) -> OptionChain | None:
    from ib_async import IB, Future, FuturesOption

    log.info("[%s] connecting to IB Gateway %s:%d (clientId=%d)",
             root, s.ibkr_host, s.ibkr_port, s.ibkr_client_id)
    ib = IB()
    try:
        ib.connect(s.ibkr_host, s.ibkr_port, clientId=s.ibkr_client_id,
                   readonly=True, timeout=15)
        # Type 3 = delayed (15min). Returns live data when the account has
        # the subscription; falls back to delayed otherwise. Without this,
        # accounts lacking real-time get -1 / NaN for everything.
        ib.reqMarketDataType(3)
        log.info("[%s] connected (market data type=delayed; live used if subscribed)", root)

        # Underlying future for the mark.
        log.info("[%s] resolving futures contract on exchange=%s", root, meta["exchange"])
        underlying = Future(symbol=root, exchange=meta["exchange"], includeExpired=False)
        details = ib.reqContractDetails(underlying)
        if not details:
            log.warning("[%s] no IBKR future details — check market data subscription for %s",
                        root, meta["exchange"])
            return None
        log.info("[%s] got %d futures contract(s)", root, len(details))

        future_contract = sorted(
            details, key=lambda d: d.contract.lastTradeDateOrContractMonth
        )[0].contract
        log.info("[%s] front-month future: %s expiry=%s conId=%d",
                 root, future_contract.localSymbol or future_contract.symbol,
                 future_contract.lastTradeDateOrContractMonth, future_contract.conId)

        ib.qualifyContracts(future_contract)
        log.info("[%s] requesting market data for underlying", root)
        ticker = ib.reqMktData(future_contract, "", snapshot=True)
        ib.sleep(2.0)
        # NaN-safe: market data farms return NaN/-1 for unsubscribed feeds.
        underlying_price = (
            _safe_price(ticker.marketPrice())
            or _safe_price(ticker.last)
            or _safe_price(ticker.close)
        )
        log.info("[%s] underlying mark: %s (last=%s close=%s bid=%s ask=%s)",
                 root, underlying_price, ticker.last, ticker.close, ticker.bid, ticker.ask)
        if underlying_price is None:
            log.warning("[%s] no underlying mark — likely missing real-time market data subscription",
                        root)
            return None
        underlying_symbol = future_contract.localSymbol or f"{root}{future_contract.lastTradeDateOrContractMonth}"

        # Resolve expiration via secdef params. The futFopExchange param is REQUIRED
        # for FUT — passing "" yields 'Error validating request: Missing exchange
        # for security type FUT' from IBKR.
        log.info("[%s] requesting option chain params (secdef, exchange=%s)",
                 root, meta["exchange"])
        all_params = ib.reqSecDefOptParams(
            future_contract.symbol, meta["exchange"], "FUT", future_contract.conId
        )
        if not all_params:
            log.warning("[%s] no option params returned (no options on this future, "
                        "or wrong sec type)", root)
            return None
        log.info("[%s] got %d secdef param entries (trading classes: %s)",
                 root, len(all_params),
                 sorted({p.tradingClass for p in all_params}))

        # Filter to entries matching our target trading class — otherwise we
        # pull weekly expirations (Monday/Wednesday/Friday weeklies have
        # different trading classes) and qualifyContracts fails with
        # 'No security definition' because we keep meta["trading_class"] fixed.
        params = [p for p in all_params if p.tradingClass == meta["trading_class"]]
        if not params:
            log.warning("[%s] no secdef params matched tradingClass=%s; "
                        "available: %s",
                        root, meta["trading_class"],
                        sorted({p.tradingClass for p in all_params}))
            return None
        log.info("[%s] %d param entries match tradingClass=%s",
                 root, len(params), meta["trading_class"])

        if expiration is not None:
            expiry_yyyymmdd = expiration.replace("-", "")
            log.info("[%s] using requested expiration %s", root, expiry_yyyymmdd)
        else:
            today_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
            # Prefer expirations >=7 days out so we don't end up with 0DTE / 2DTE
            # unless the operator explicitly wants them.
            min_str = (datetime.now(tz=timezone.utc).date()
                       .replace(day=1)).isoformat()  # placeholder, set below
            from datetime import timedelta as _td
            min_dt = (datetime.now(tz=timezone.utc).date() + _td(days=7))
            min_str = min_dt.strftime("%Y%m%d")
            all_expiries = sorted({e for p in params for e in p.expirations})
            future_expiries = [e for e in all_expiries if e >= min_str]
            if not future_expiries:
                # Fall back to any future expiration if 7-day floor leaves nothing.
                future_expiries = [e for e in all_expiries if e >= today_str]
            if not future_expiries:
                log.warning("[%s] no expirations >= today in secdef params", root)
                return None
            expiry_yyyymmdd = future_expiries[0]
            log.info("[%s] auto-selected expiration %s (>=7d out, %d available)",
                     root, expiry_yyyymmdd, len(future_expiries))
        expiration_d = date(int(expiry_yyyymmdd[:4]),
                             int(expiry_yyyymmdd[4:6]),
                             int(expiry_yyyymmdd[6:8]))

        if strikes is None:
            all_strikes = sorted({k for p in params for k in p.strikes})
            log.info("[%s] %d strikes available in tradingClass=%s",
                     root, len(all_strikes), meta["trading_class"])
            atm = min(all_strikes, key=lambda k: abs(k - underlying_price))
            atm_idx = all_strikes.index(atm)
            half = num_strikes // 2
            chosen = all_strikes[max(0, atm_idx - half): atm_idx + half + 1]
            log.info("[%s] picked %d strikes around ATM=%s: %s",
                     root, len(chosen), atm, chosen)
        else:
            chosen = sorted(set(strikes))
            log.info("[%s] using %d caller-supplied strikes: %s", root, len(chosen), chosen)

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
        log.info("[%s] qualifying %d option contracts (%d strikes × C+P)...",
                 root, len(option_contracts), len(chosen))
        ib.qualifyContracts(*option_contracts)
        qualified_count = sum(1 for c in option_contracts if getattr(c, "conId", 0))
        log.info("[%s] %d/%d contracts qualified", root, qualified_count, len(option_contracts))

        log.info("[%s] requesting market data for %d option contracts (genericTickList=106)...",
                 root, len(option_contracts))
        tickers = [ib.reqMktData(c, "106", snapshot=False, regulatorySnapshot=False)
                   for c in option_contracts]
        ib.sleep(3.0)

        contracts: list[OptionContract] = []
        dropped_no_quote = 0
        dropped_no_greeks_no_compute = 0
        dropped_validation = 0
        computed_greeks = 0
        now_utc = datetime.now(tz=timezone.utc)
        today = now_utc.date()
        T_years = max((expiration_d - today).days / 365.25, 1.0 / 365.25)

        for contract, t in zip(option_contracts, tickers):
            bid = _safe_price(t.bid)
            ask = _safe_price(t.ask)
            if bid is None or ask is None:
                dropped_no_quote += 1
                continue
            last = _safe_price(t.last)
            mid = (bid + ask) / 2.0
            ot = OptionType(contract.right)

            greeks = t.modelGreeks
            if _greeks_complete(greeks):
                iv = float(greeks.impliedVol)
                delta = float(greeks.delta)
                gamma = float(greeks.gamma)
                theta = float(greeks.theta)
                vega = float(greeks.vega)
            else:
                # Compute Greeks ourselves via Black-76 from the mid price.
                try:
                    iv = implied_vol(
                        F=float(underlying_price), K=float(contract.strike),
                        market_price=mid, T=T_years, r=0.05, option_type=ot,
                    )
                    b76 = black76(
                        F=float(underlying_price), K=float(contract.strike),
                        sigma=iv, T=T_years, r=0.05, option_type=ot,
                    )
                    delta = b76.delta
                    gamma = b76.gamma
                    theta = b76.theta / 365.0   # per-day (matches OptionContract convention)
                    vega = b76.vega / 100.0     # per 1% point of vol
                    computed_greeks += 1
                except Exception as e:
                    log.debug("[%s] Black-76 compute failed for %s%s mid=%s: %s",
                              root, contract.strike, contract.right, mid, e)
                    dropped_no_greeks_no_compute += 1
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
                    bid=bid, ask=ask, last=last,
                    iv=iv, delta=delta, gamma=gamma, theta=theta, vega=vega,
                    volume=int(t.volume) if t.volume else 0,
                    open_interest=0,  # IBKR exposes OI on a separate tick type; v1 leaves at 0
                    quote_time=now_utc,
                ))
            except Exception as e:
                dropped_validation += 1
                log.debug("[%s] dropped %s%s: %s",
                          root, contract.strike, contract.right, e)
                continue

        log.info("[%s] kept %d contracts | computed_greeks=%d | "
                 "dropped: no_quote=%d compute_failed=%d validation=%d",
                 root, len(contracts), computed_greeks,
                 dropped_no_quote, dropped_no_greeks_no_compute, dropped_validation)

        if not contracts:
            log.warning("[%s] IBKR returned no usable contracts — likely missing OPRA/CME "
                        "real-time market data subscription, or market closed.", root)
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
            log.info("[%s] disconnected", root)
        except Exception:
            pass
