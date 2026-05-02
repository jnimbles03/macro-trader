"""Missing/stale chain must produce NO TRADE — never an estimated IV fallback."""

from datetime import date, datetime, timedelta, timezone

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


def _idea():
    legs = [
        TradeLeg(action="BUY", quantity=1, option_type=OptionType.PUT, strike=110.0,
                  expiration=date(2026, 5, 23), premium=0.49, iv=0.07, delta=-0.49,
                  gamma=0.21, theta=-0.005, vega=0.1),
        TradeLeg(action="SELL", quantity=1, option_type=OptionType.PUT, strike=108.5,
                  expiration=date(2026, 5, 23), premium=0.12, iv=0.07, delta=-0.18,
                  gamma=0.10, theta=-0.0028, vega=0.07),
    ]
    return TradeIdea(
        kind=TradeKind.DEFINED_RISK_SPREAD,
        name="zn bear put", root="ZN", underlying_symbol="ZNM6", direction="bearish",
        structure=SpreadStructure.BEAR_PUT_SPREAD, expiration=date(2026, 5, 23), legs=legs,
        entry_debit_credit=0.37, max_loss=370.0, max_profit=1130.0, breakeven=[109.63],
        rr_ratio=3.05, bid_ask_pct_worst=0.02, min_volume=200, min_open_interest=2000,
        catalyst="x", causal_chain="x", why_this_structure="x", what_kills_thesis="x",
        invalidation="x", stop_logic="x", profit_taking_logic="x",
    )


def test_missing_chain_rejected():
    with pytest.raises(RiskRejection) as ei:
        validate_trade(_idea(), None)
    assert ei.value.reason == NoTradeReason.MISSING_CHAIN_DATA


def test_stale_chain_rejected():
    qt = datetime.utcnow() - timedelta(minutes=15)        # > 5 min stale window
    chain = OptionChain(root="ZN", underlying_symbol="ZNM6", underlying_price=110.0,
                        expiration=date(2026, 5, 23), quote_time=qt, multiplier=1000.0,
                        contracts=[OptionContract(
                            root="ZN", underlying_symbol="ZNM6", underlying_price=110.0,
                            option_type=OptionType.PUT, strike=110.0, expiration=date(2026, 5, 23),
                            multiplier=1000.0, bid=0.485, ask=0.495, iv=0.072, delta=-0.49,
                            gamma=0.21, theta=-0.005, vega=0.105, volume=1240, open_interest=8200,
                            quote_time=qt)])
    with pytest.raises(RiskRejection) as ei:
        validate_trade(_idea(), chain)
    assert ei.value.reason == NoTradeReason.STALE_QUOTES
