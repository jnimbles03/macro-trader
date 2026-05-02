"""IBKR option chain snapshot ingest.

Connects to IB Gateway / TWS via ib_async, pulls a single options-on-futures
chain (root + expiration), and persists it to `option_chains` +
`option_contracts`. No backfill — chains are point-in-time data.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from app.config import get_settings
from app.models.option_contract import OptionChain, OptionContract, OptionType
from app.storage.repository import upsert_chain

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

    ib = IB()
    try:
        ib.connect(s.ibkr_host, s.ibkr_port, clientId=s.ibkr_client_id,
                   readonly=True, timeout=15)

        # Underlying future for the mark.
        underlying = Future(symbol=root, exchange=meta["exchange"], includeExpired=False)
        details = ib.reqContractDetails(underlying)
        if not details:
            log.warning("no IBKR future details for %s", root)
            return None

        future_contract = sorted(
            details, key=lambda d: d.contract.lastTradeDateOrContractMonth
        )[0].contract
        ib.qualifyContracts(future_contract)
        ticker = ib.reqMktData(future_contract, "", snapshot=True)
        ib.sleep(2.0)
        underlying_price = ticker.marketPrice()
        if underlying_price is None or underlying_price != underlying_price:
            underlying_price = ticker.last or ticker.close
        if not underlying_price:
            log.warning("no underlying mark for %s", root)
            return None
        underlying_symbol = future_contract.localSymbol or f"{root}{future_contract.lastTradeDateOrContractMonth}"

        # Resolve expiration via secdef params.
        params = ib.reqSecDefOptParams(
            future_contract.symbol, "", "FUT", future_contract.conId
        )
        if not params:
            log.warning("no option params for %s", root)
            return None

        if expiration is not None:
            expiry_yyyymmdd = expiration.replace("-", "")
        else:
            all_expiries = sorted({e for p in params for e in p.expirations})
            if not all_expiries:
                log.warning("no expirations for %s", root)
                return None
            expiry_yyyymmdd = all_expiries[0]
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
        ib.sleep(3.0)

        contracts: list[OptionContract] = []
        now_utc = datetime.now(tz=timezone.utc)
        for contract, t in zip(option_contracts, tickers):
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
                    expiration=expiration_d,
                    multiplier=meta["multiplier"],
                    bid=float(bid), ask=float(ask),
                    last=float(t.last) if t.last else None,
                    iv=float(greeks.impliedVol),
                    delta=float(greeks.delta),
                    gamma=float(greeks.gamma),
                    theta=float(greeks.theta),
                    vega=float(greeks.vega),
                    volume=int(t.volume) if t.volume else 0,
                    open_interest=0,  # IBKR exposes OI on a separate tick type; v1 leaves at 0
                    quote_time=now_utc,
                ))
            except Exception as e:
                log.debug("dropping IBKR contract %s %s: %s",
                          contract.strike, contract.right, e)
                continue

        if not contracts:
            log.warning("IBKR returned no usable contracts for %s", root)
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
