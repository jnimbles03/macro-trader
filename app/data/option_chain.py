"""Option chain query layer.

Reads from the warehouse `option_chains` + `option_contracts` tables by
default. `live=True` bypasses and pulls a fresh snapshot from IBKR (and
persists it to the warehouse).

Mock mode reads `fixtures/{root}_option_chain.json` and stamps `quote_time`
to now() so the staleness gate doesn't fire deterministically in tests.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from app.config import get_settings
from app.data.cache import cache_key, cached_call
from app.models.option_contract import OptionChain, OptionContract, OptionType
from app.storage.repository import latest_chain

log = logging.getLogger(__name__)


def fetch_chains_for_candidates(candidates: list[dict], *, fresh: bool = False,
                                 live: bool = False) -> dict[str, OptionChain]:
    """Return {root: OptionChain} for every distinct root in the candidate list."""
    s = get_settings()
    by_root: dict[str, list[dict]] = {}
    for c in candidates:
        root = (c.get("root") or "").upper()
        if not root:
            continue
        by_root.setdefault(root, []).append(c)

    out: dict[str, OptionChain] = {}
    for root, cands in by_root.items():
        key = cache_key("chain", root, "live" if live else "warehouse",
                        "mock" if s.mock_data else "real")
        chain = cached_call(
            key,
            ttl_seconds=s.cache_chain_min * 60,
            fresh=fresh,
            loader=lambda r=root, cs=cands: _load_chain(r, cs, live=live),
        )
        if chain is not None:
            out[root] = chain
    return out


def _load_chain(root: str, candidates: list[dict], *, live: bool) -> OptionChain | None:
    s = get_settings()
    if s.mock_data:
        return _load_fixture_chain(root)

    if live:
        chain = _live_snapshot(root, candidates)
        if chain is not None:
            return chain
        # Fall through to warehouse if live failed.

    expirations = sorted({c["expiration"] for c in candidates if c.get("expiration")})
    expiration_d = date.fromisoformat(expirations[0]) if expirations else None
    return latest_chain(root, expiration_d)


def _live_snapshot(root: str, candidates: list[dict]) -> OptionChain | None:
    """Trigger an IBKR ingest for this root's expiration + needed strikes,
    then return the freshly-written warehouse row."""
    from app.ingest import ibkr_chain
    from app.ingest.runner import run_one

    expirations = sorted({c["expiration"] for c in candidates if c.get("expiration")})
    if not expirations:
        log.warning("no expiration in candidates for %s", root)
        return None
    expiration = expirations[0]
    strikes = sorted({float(leg["strike"])
                      for c in candidates
                      for leg in c.get("legs", []) if leg.get("strike") is not None})
    run_one(f"ibkr:{root}", ibkr_chain.ingest, root=root, expiration=expiration,
            strikes=strikes if strikes else None)
    return latest_chain(root, date.fromisoformat(expiration))


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
