"""Volatility surface helpers — strictly read-only over chain data.

No IV fallback to historical vol.
"""

from __future__ import annotations

from app.models.option_contract import OptionChain, OptionType


def expected_move_pct(chain: OptionChain) -> float | None:
    """Approximate ATM straddle / underlying.

    Returns None if ATM call/put not available — caller must NO TRADE rather than
    estimate.
    """
    F = chain.underlying_price
    atm_strike = min((c.strike for c in chain.contracts), key=lambda k: abs(k - F))
    call = chain.find(atm_strike, OptionType.CALL)
    put = chain.find(atm_strike, OptionType.PUT)
    if call is None or put is None:
        return None
    straddle = call.mid + put.mid
    return round(straddle / F, 4)
