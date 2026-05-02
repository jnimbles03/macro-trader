"""Payoff math for vertical spreads + single longs."""

from datetime import date

import pytest

from app.analysis.payoff_engine import (
    metrics_for_structure,
    single_long_metrics,
    vertical_spread_metrics,
)
from app.models.option_contract import OptionType
from app.models.trade_idea import SpreadStructure, TradeLeg


def _leg(action, ot, strike, premium):
    return TradeLeg(
        action=action, quantity=1, option_type=ot, strike=strike,
        expiration=date(2026, 5, 23), premium=premium,
        iv=0.07, delta=-0.4, gamma=0.1, theta=-0.005, vega=0.1,
    )


def test_bear_put_spread_metrics():
    legs = [_leg("BUY", OptionType.PUT, 110.0, 0.49), _leg("SELL", OptionType.PUT, 108.5, 0.12)]
    m = vertical_spread_metrics(legs)
    assert m.net_debit == pytest.approx(0.37)
    assert m.max_loss == pytest.approx(0.37)
    assert m.max_profit == pytest.approx(1.5 - 0.37)
    assert m.breakeven[0] == pytest.approx(110.0 - 0.37)


def test_bull_call_spread_credit_vs_debit():
    legs_debit = [_leg("BUY", OptionType.CALL, 100.0, 5.0), _leg("SELL", OptionType.CALL, 105.0, 2.5)]
    m_d = vertical_spread_metrics(legs_debit)
    assert m_d.max_loss == pytest.approx(2.5)
    assert m_d.max_profit == pytest.approx(2.5)
    assert m_d.breakeven[0] == pytest.approx(102.5)

    legs_credit = [_leg("SELL", OptionType.CALL, 100.0, 5.0), _leg("BUY", OptionType.CALL, 105.0, 2.5)]
    m_c = vertical_spread_metrics(legs_credit)
    assert m_c.max_profit == pytest.approx(2.5)             # credit received
    assert m_c.max_loss == pytest.approx(2.5)               # width - credit
    assert m_c.breakeven[0] == pytest.approx(102.5)


def test_single_long_call():
    leg = _leg("BUY", OptionType.CALL, 100.0, 1.5)
    m = single_long_metrics(leg)
    assert m.max_loss == pytest.approx(1.5)
    assert m.breakeven[0] == pytest.approx(101.5)
    assert m.max_profit == float("inf")


def test_metrics_for_structure_dispatch():
    legs = [_leg("BUY", OptionType.PUT, 110.0, 0.49), _leg("SELL", OptionType.PUT, 108.5, 0.12)]
    m = metrics_for_structure(SpreadStructure.BEAR_PUT_SPREAD, legs)
    assert m.max_loss == pytest.approx(0.37)
