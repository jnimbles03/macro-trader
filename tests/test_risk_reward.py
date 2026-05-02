"""Spread with rr_ratio < 2.0 must be rejected by the risk engine."""

from datetime import date, datetime, timedelta

import pytest

from app.analysis.risk_engine import RiskRejection, validate_trade
from app.models.option_contract import OptionChain, OptionContract, OptionType
from app.models.trade_idea import (
    NoTradeReason,
    SpreadStructure,
    TradeIdea,
    TradeKind,
    TradeLeg,
)


def _chain():
    qt = datetime.utcnow() - timedelta(seconds=5)
    contracts = [
        OptionContract(root="ES", underlying_symbol="ESM6", underlying_price=5180.0,
                        option_type=OptionType.PUT, strike=5180.0, expiration=date(2026, 5, 30),
                        multiplier=50.0, bid=42.00, ask=42.50, iv=0.16, delta=-0.49,
                        gamma=0.0019, theta=-0.95, vega=8.1, volume=4000, open_interest=20000,
                        quote_time=qt),
        OptionContract(root="ES", underlying_symbol="ESM6", underlying_price=5180.0,
                        option_type=OptionType.PUT, strike=5100.0, expiration=date(2026, 5, 30),
                        multiplier=50.0, bid=22.00, ask=22.40, iv=0.17, delta=-0.30,
                        gamma=0.0018, theta=-0.78, vega=7.4, volume=3000, open_interest=20000,
                        quote_time=qt),
    ]
    return OptionChain(root="ES", underlying_symbol="ESM6", underlying_price=5180.0,
                       expiration=date(2026, 5, 30), quote_time=qt, contracts=contracts,
                       multiplier=50.0)


def test_low_rr_spread_rejected():
    # Buy 5180P @ 42.25, sell 5100P @ 22.20: net debit 20.05; width 80; max_profit 59.95;
    # rr = 59.95/20.05 ≈ 2.99 — passes. Construct an artificially bad rr to trigger.
    legs = [
        TradeLeg(action="BUY", quantity=1, option_type=OptionType.PUT, strike=5180.0,
                  expiration=date(2026, 5, 30), premium=42.25, iv=0.16, delta=-0.49,
                  gamma=0.0019, theta=-0.95, vega=8.1),
        TradeLeg(action="SELL", quantity=1, option_type=OptionType.PUT, strike=5100.0,
                  expiration=date(2026, 5, 30), premium=22.20, iv=0.17, delta=-0.30,
                  gamma=0.0018, theta=-0.78, vega=7.4),
    ]
    # max_loss/max_profit forced to give rr=1.0 (bypasses pydantic ge=2 by directly setting)
    with pytest.raises(ValueError):                                # pydantic-level rejection
        TradeIdea(
            kind=TradeKind.DEFINED_RISK_SPREAD,
            name="bad rr",
            root="ES", underlying_symbol="ESM6", direction="bearish",
            structure=SpreadStructure.BEAR_PUT_SPREAD,
            expiration=date(2026, 5, 30), legs=legs,
            entry_debit_credit=20.05, max_loss=1000.0, max_profit=999.0, breakeven=[5159.95],
            rr_ratio=0.99, bid_ask_pct_worst=0.01, min_volume=100, min_open_interest=200,
            catalyst="x", causal_chain="x", why_this_structure="x",
            what_kills_thesis="x", invalidation="x", stop_logic="x", profit_taking_logic="x",
        )


def test_engine_rejects_low_rr_via_runtime_check():
    """Build an idea that passes pydantic (rr=2.01) and then mutate to verify engine path."""
    chain = _chain()
    legs = [
        TradeLeg(action="BUY", quantity=1, option_type=OptionType.PUT, strike=5180.0,
                  expiration=date(2026, 5, 30), premium=42.25, iv=0.16, delta=-0.49,
                  gamma=0.0019, theta=-0.95, vega=8.1),
        TradeLeg(action="SELL", quantity=1, option_type=OptionType.PUT, strike=5100.0,
                  expiration=date(2026, 5, 30), premium=22.20, iv=0.17, delta=-0.30,
                  gamma=0.0018, theta=-0.78, vega=7.4),
    ]
    idea = TradeIdea(
        kind=TradeKind.DEFINED_RISK_SPREAD,
        name="ok",
        root="ES", underlying_symbol="ESM6", direction="bearish",
        structure=SpreadStructure.BEAR_PUT_SPREAD,
        expiration=date(2026, 5, 30), legs=legs,
        entry_debit_credit=20.05, max_loss=1000.0, max_profit=2010.0, breakeven=[5159.95],
        rr_ratio=2.01, bid_ask_pct_worst=0.01, min_volume=100, min_open_interest=200,
        catalyst="x", causal_chain="x", why_this_structure="x", what_kills_thesis="x",
        invalidation="x", stop_logic="x", profit_taking_logic="x",
    )
    # Mutate rr_ratio below floor and pass to engine
    bad = idea.model_copy(update={"rr_ratio": 1.5})
    with pytest.raises(RiskRejection) as ei:
        validate_trade(bad, chain)
    assert ei.value.reason == NoTradeReason.RR_BELOW_FLOOR
