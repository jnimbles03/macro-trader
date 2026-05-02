"""Option chain hydration.

Live mode: pulls options-on-futures chains from Interactive Brokers via
ib_async (the actively-maintained fork of ib_insync). Requires IB Gateway or
TWS running locally with the API enabled.

Mock mode: reads `fixtures/{root}_option_chain.json` and stamps quote_time to
now() so the staleness gate doesn't fire deterministically in tests.

We never fabricate prices, IV, or Greeks. Anything missing => the contract is
dropped from the chain (and the trade selector returns NO TRADE if the strike
the LLM wanted isn't there).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from app.config import get_settings
from app.data.cache import cache_key, cached_call
from app.models.option_contract import OptionChain, OptionContract, OptionType

log = logging.getLogger(__name__)


# IBKR exchange + multiplier per root. Source: IBKR contract specs.
_IBKR_META: dict[str, dict[str, Any]] = {
    # Treasuries (CBOT)
    "ZN": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OZN"},
    "ZF": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OZF"},
    "ZB": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OZB"},
    "ZT": {"exchange": "CBOT", "multiplier": 2000.0, "trading_class": "OZT"},
    "TN": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OTN"},
    "UB": {"exchange": "CBOT", "multiplier": 1000.0, "trading_class": "OUB"},
    # Equity index (CME)
    "ES": {"exchange": "CME", "multiplier": 50.0, "trading_class": "ES"},
    "NQ": {"exchange": "CME", "multiplier": 20.0, "trading_class": "NQ"},
    "RTY": {"exchange": "CME", "multiplier": 50.0, "trading_class": "RTY"},
    # Energy (NYMEX)
    "CL": {"exchange": "NYMEX", "multiplier": 1000.0, "trading_class": "LO"},
    "NG": {"exchange": "NYMEX", "multiplier": 10000.0, "trading_class": "ON"},
    # Metals (COMEX)
    "GC": {"exchange": "COMEX", "multiplier": 100.0, "trading_class": "OG"},
    "SI": {"exchange": "COMEX", "multiplier": 5000.0, "trading_class": "SO"},
    "HG": {"exchange": "COMEX", "multiplier": 25000.0, "trading_class": "HXE"},
    # FX (CME)
    "6E": {"exchange": "CME", "multiplier": 125000.0, "trading_class": "EUU"},
    "6J": {"exchange": "CME", "multiplier": 12500000.0, "trading_class": "JPU"},
    "6B": {"exchange": "CME", "multiplier": 62500.0, "trading_class": "GBU"},
    "6A": {"exchange": "CME", "multiplier": 100000.0, "trading_class": "ADU"},
    "6C": {"exchange": "CME", "multiplier": 100000.0, "trading_class": "CAU"},
    "6S": {"exchange": "CME", "multiplier": 125000.0, "trading_class": "CHU"},
    # VX (CFE) — flagged separately upstream; included so chain lookup doesn't crash.
    "VX": {"exchange": "CFE", "multiplier": 1000.0, "trading_class": "VX"},
}


def fetch_chains_for_candidates(candidates: list[dict], *, fresh: bool = False) -> dict[str, OptionChain]:
    """Return {root: OptionChain} for every distinct root in the candidate list.

    Each chain only includes the strikes the candidate asked for (plus a small
    neighborhood) — keeps live IBKR fan-out tight. Mock mode loads the full
    fixture chain since it's already small.
    """
    s = get_settings()
    by_root: dict[str, list[dict]] = {}
    for c in candidates:
        root = (c.get("root") or "").upper()
        if not root:
            continue
        by_root.setdefault(root, []).append(c)

    out: dict[str, OptionChain] = {}
    for root, cands in by_root.items():
        key = cache_key("chain", root, "mock" if s.mock_data else "live", fresh)
        chain = cached_call(
            key,
            ttl_seconds=s.cache_chain_min * 60,
            fresh=fresh,
            loader=lambda r=root, cs=cands: _load_chain(r, cs),
        )
        if chain is not None:
            out[root] = chain
    return out


def _load_chain(root: str, candidates: list[dict]) -> OptionChain | None:
    s = get_settings()
    if s.mock_data:
        return _load_fixture_chain(root)
    if not s.ibkr_enabled:
        log.warning("IBKR_ENABLED=false and MOCK_DATA=false — no chain source for %s", root)
        return None
    try:
        return _fetch_ibkr_chain(root, candidates)
    except Exception as e:
        log.warning("IBKR chain fetch failed for %s: %s", root, e)
        return None


# ---------------------------------------------------------------------------
# Mock loader — fixtures with quote_time stamped to now() so staleness gate
# never fires deterministically in tests.
# ---------------------------------------------------------------------------
def _load_fixture_chain(root: str) -> OptionChain | None:
    s = get_settings()
    path = s.fixtures_dir / f"{root.lower()}_option_chain.json"
    if not path.exists():
        log.info("no fixture chain for %s at %s", root, path)
        return None
    raw = json.loads(path.read_text())
    expiration = date.fromisoformat(raw["expiration"])
    multiplier = float(raw["multiplier"])
    underlying_price = float(raw["underlying_price"])
    underlying_symbol = raw["underlying_symbol"]
    quote_time = datetime.now(tz=timezone.utc)
    risk_free_rate = float(raw.get("risk_free_rate", 0.05))
    tick_size = float(raw.get("tick_size", 0.01))

    contracts: list[OptionContract] = []
    for c in raw["contracts"]:
        contracts.append(OptionContract(
            root=root,
            underlying_symbol=underlying_symbol,
            underlying_price=underlying_price,
            option_type=OptionType(c["option_type"]),
            strike=float(c["strike"]),
            expiration=expiration,
            multiplier=multiplier,
            bid=float(c["bid"]),
            ask=float(c["ask"]),
            iv=float(c["iv"]),
            delta=float(c["delta"]),
            gamma=float(c["gamma"]),
            theta=float(c["theta"]),
            vega=float(c["vega"]),
            volume=int(c.get("volume", 0)),
            open_interest=int(c.get("open_interest", 0)),
            quote_time=quote_time,
            risk_free_rate=risk_free_rate,
            tick_size=tick_size,
        ))
    return OptionChain(
        root=root,
        underlying_symbol=underlying_symbol,
        underlying_price=underlying_price,
        expiration=expiration,
        quote_time=quote_time,
        contracts=contracts,
        multiplier=multiplier,
    )


# ---------------------------------------------------------------------------
# IBKR live loader (ib_async). Pulls only the strikes asked for; relies on the
# user running IB Gateway or TWS locally with API enabled.
# ---------------------------------------------------------------------------
def _fetch_ibkr_chain(root: str, candidates: list[dict]) -> OptionChain | None:
    meta = _IBKR_META.get(root)
    if meta is None:
        log.warning("no IBKR contract metadata for root %s", root)
        return None

    # Imported lazily so mock-mode users + the test suite don't pay the
    # ib_async import cost (and don't need it installed).
    from ib_async import IB, Future, FuturesOption

    s = get_settings()

    expirations = sorted({c["expiration"] for c in candidates if c.get("expiration")})
    if not expirations:
        log.warning("no expiration in candidates for %s", root)
        return None
    expiration = date.fromisoformat(expirations[0])
    expiry_yyyymmdd = expiration.strftime("%Y%m%d")

    wanted_strikes = sorted({float(leg["strike"])
                             for c in candidates
                             for leg in c.get("legs", []) if leg.get("strike") is not None})
    if not wanted_strikes:
        log.warning("no strikes in candidates for %s", root)
        return None

    ib = IB()
    try:
        ib.connect(s.ibkr_host, s.ibkr_port, clientId=s.ibkr_client_id, readonly=True, timeout=15)

        # 1. Resolve the front-month underlying future for the mark.
        underlying_future = Future(symbol=root, exchange=meta["exchange"], includeExpired=False)
        details = ib.reqContractDetails(underlying_future)
        if not details:
            log.warning("no IBKR future contract details for %s", root)
            return None
        # Pick the future whose expiry is the earliest >= the option expiry.
        future_contract = None
        for d in sorted(details, key=lambda d: d.contract.lastTradeDateOrContractMonth):
            if d.contract.lastTradeDateOrContractMonth >= expiry_yyyymmdd[:6]:
                future_contract = d.contract
                break
        if future_contract is None:
            future_contract = sorted(details, key=lambda d: d.contract.lastTradeDateOrContractMonth)[-1].contract

        ib.qualifyContracts(future_contract)
        ticker = ib.reqMktData(future_contract, "", snapshot=True)
        ib.sleep(2.0)
        underlying_price = ticker.marketPrice()
        if underlying_price is None or underlying_price != underlying_price:  # NaN check
            underlying_price = ticker.last or ticker.close
        if not underlying_price:
            log.warning("no underlying mark for %s", root)
            return None
        underlying_symbol = future_contract.localSymbol or f"{root}{future_contract.lastTradeDateOrContractMonth}"

        # 2. Build option contracts for the requested strikes (both calls + puts so the
        #    selector can resolve either side).
        option_contracts: list[Any] = []
        for strike in wanted_strikes:
            for right in ("C", "P"):
                opt = FuturesOption(
                    symbol=root,
                    lastTradeDateOrContractMonth=expiry_yyyymmdd,
                    strike=strike,
                    right=right,
                    exchange=meta["exchange"],
                    multiplier=str(int(meta["multiplier"])),
                    tradingClass=meta["trading_class"],
                )
                option_contracts.append(opt)
        ib.qualifyContracts(*option_contracts)

        # 3. Snapshot quotes + greeks. genericTickList "106" requests option computations.
        tickers = [ib.reqMktData(c, "106", snapshot=False, regulatorySnapshot=False)
                   for c in option_contracts]
        ib.sleep(3.0)  # allow snapshots to populate

        contracts: list[OptionContract] = []
        now_utc = datetime.now(tz=timezone.utc)
        for contract, t in zip(option_contracts, tickers):
            # Greeks come on modelGreeks (or bid/askGreeks if available).
            greeks = t.modelGreeks
            if greeks is None or any(getattr(greeks, k, None) is None
                                     for k in ("impliedVol", "delta", "gamma", "theta", "vega")):
                continue
            bid = t.bid if t.bid is not None and t.bid > 0 else None
            ask = t.ask if t.ask is not None and t.ask > 0 else None
            if bid is None or ask is None:
                continue
            try:
                contracts.append(OptionContract(
                    root=root,
                    underlying_symbol=underlying_symbol,
                    underlying_price=float(underlying_price),
                    option_type=OptionType(contract.right),
                    strike=float(contract.strike),
                    expiration=expiration,
                    multiplier=meta["multiplier"],
                    bid=float(bid),
                    ask=float(ask),
                    last=float(t.last) if t.last else None,
                    iv=float(greeks.impliedVol),
                    delta=float(greeks.delta),
                    gamma=float(greeks.gamma),
                    theta=float(greeks.theta),
                    vega=float(greeks.vega),
                    volume=int(t.volume) if t.volume else 0,
                    open_interest=int(getattr(t, "callOpenInterest", 0) or getattr(t, "putOpenInterest", 0) or 0),
                    quote_time=now_utc,
                ))
            except Exception as e:
                log.debug("dropping IBKR contract %s %s: %s", contract.strike, contract.right, e)
                continue

        if not contracts:
            log.warning("IBKR returned no usable contracts for %s", root)
            return None

        return OptionChain(
            root=root,
            underlying_symbol=underlying_symbol,
            underlying_price=float(underlying_price),
            expiration=expiration,
            quote_time=now_utc,
            contracts=contracts,
            multiplier=meta["multiplier"],
        )
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass
