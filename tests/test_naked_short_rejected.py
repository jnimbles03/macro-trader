"""Naked short options must be rejected in BOTH slots."""

from datetime import date

import pytest

from app.models.option_contract import OptionType
from app.models.trade_idea import (
    SpreadStructure,
    TradeIdea,
    TradeKind,
    TradeLeg,
)


def _short_only_legs():
    return [TradeLeg(
        action="SELL", quantity=1, option_type=OptionType.CALL, strike=5200.0,
        expiration=date(2026, 5, 30), premium=20.0, iv=0.15, delta=0.40,
        gamma=0.0015, theta=-0.7, vega=7.0,
    )]


def test_naked_short_in_defined_risk_slot_rejected():
    with pytest.raises(ValueError):
        TradeIdea(
            kind=TradeKind.DEFINED_RISK_SPREAD, name="naked short", root="ES",
            underlying_symbol="ESM6", direction="bearish",
            structure=SpreadStructure.CALL_CREDIT_SPREAD, expiration=date(2026, 5, 30),
            legs=_short_only_legs(),
            entry_debit_credit=-20.0, max_loss=10000.0, max_profit=20000.0, breakeven=[5220.0],
            rr_ratio=2.0, bid_ask_pct_worst=0.01, min_volume=100, min_open_interest=200,
            catalyst="x", causal_chain="x", why_this_structure="x", what_kills_thesis="x",
            invalidation="x", stop_logic="x", profit_taking_logic="x",
        )


def test_naked_short_in_yolo_slot_rejected():
    with pytest.raises(ValueError):
        TradeIdea(
            kind=TradeKind.YOLO_LONG, name="naked yolo short", root="ES",
            underlying_symbol="ESM6", direction="bearish",
            structure=SpreadStructure.SINGLE_LONG, expiration=date(2026, 5, 30),
            legs=_short_only_legs(),
            entry_debit_credit=-20.0, max_loss=10000.0, max_profit=20000.0, breakeven=[5220.0],
            rr_ratio=2.0, bid_ask_pct_worst=0.01, min_volume=100, min_open_interest=200,
            catalyst="x", causal_chain="x", why_this_structure="x", what_kills_thesis="x",
            invalidation="x", stop_logic="x", profit_taking_logic="x",
            why_probably_dumb="naked short fantasy",
        )
