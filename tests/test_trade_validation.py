"""Pydantic-level guards on TradeIdea."""

from datetime import date

import pytest

from app.models.option_contract import OptionType
from app.models.trade_idea import (
    SpreadStructure,
    TradeIdea,
    TradeKind,
    TradeLeg,
)


def _yolo_leg():
    return TradeLeg(action="BUY", quantity=1, option_type=OptionType.PUT, strike=4900.0,
                    expiration=date(2026, 5, 30), premium=6.55, iv=0.20, delta=-0.10,
                    gamma=0.001, theta=-0.4, vega=4.9)


def test_yolo_requires_why_probably_dumb():
    with pytest.raises(ValueError):
        TradeIdea(
            kind=TradeKind.YOLO_LONG, name="x", root="ES", underlying_symbol="ESM6",
            direction="bearish", structure=SpreadStructure.SINGLE_LONG, expiration=date(2026, 5, 30),
            legs=[_yolo_leg()],
            entry_debit_credit=6.55, max_loss=327.5, max_profit=1e9, breakeven=[4893.45],
            rr_ratio=1e6, bid_ask_pct_worst=0.01, min_volume=100, min_open_interest=200,
            catalyst="x", causal_chain="x", why_this_structure="x", what_kills_thesis="x",
            invalidation="x", stop_logic="x", profit_taking_logic="x",
            why_probably_dumb=None,
        )


def test_yolo_must_be_single_long():
    bad = TradeLeg(action="SELL", quantity=1, option_type=OptionType.PUT, strike=4900.0,
                    expiration=date(2026, 5, 30), premium=6.55, iv=0.20, delta=0.10,
                    gamma=0.001, theta=-0.4, vega=4.9)
    with pytest.raises(ValueError):
        TradeIdea(
            kind=TradeKind.YOLO_LONG, name="x", root="ES", underlying_symbol="ESM6",
            direction="bearish", structure=SpreadStructure.SINGLE_LONG, expiration=date(2026, 5, 30),
            legs=[bad],
            entry_debit_credit=-6.55, max_loss=1.0, max_profit=1.0, breakeven=[0.0],
            rr_ratio=1.0, bid_ask_pct_worst=0.01, min_volume=100, min_open_interest=200,
            catalyst="x", causal_chain="x", why_this_structure="x", what_kills_thesis="x",
            invalidation="x", stop_logic="x", profit_taking_logic="x",
            why_probably_dumb="bad bet",
        )


def test_defined_risk_rr_floor_enforced_at_model_level():
    legs = [
        TradeLeg(action="BUY", quantity=1, option_type=OptionType.PUT, strike=110.0,
                 expiration=date(2026, 5, 23), premium=0.49, iv=0.07, delta=-0.49,
                 gamma=0.21, theta=-0.005, vega=0.1),
        TradeLeg(action="SELL", quantity=1, option_type=OptionType.PUT, strike=108.5,
                 expiration=date(2026, 5, 23), premium=0.12, iv=0.07, delta=-0.18,
                 gamma=0.10, theta=-0.0028, vega=0.07),
    ]
    with pytest.raises(ValueError):
        TradeIdea(
            kind=TradeKind.DEFINED_RISK_SPREAD, name="bad",
            root="ZN", underlying_symbol="ZNM6", direction="bearish",
            structure=SpreadStructure.BEAR_PUT_SPREAD, expiration=date(2026, 5, 23), legs=legs,
            entry_debit_credit=0.37, max_loss=370.0, max_profit=400.0, breakeven=[109.63],
            rr_ratio=1.08, bid_ask_pct_worst=0.02, min_volume=200, min_open_interest=2000,
            catalyst="x", causal_chain="x", why_this_structure="x", what_kills_thesis="x",
            invalidation="x", stop_logic="x", profit_taking_logic="x",
        )
