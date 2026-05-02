"""Payoff math at expiration for verticals, calendars, ratios, and singles."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.option_contract import OptionType
from app.models.trade_idea import SpreadStructure, TradeLeg


@dataclass
class PayoffResult:
    max_profit: float       # in option-price units (per 1 contract before multiplier)
    max_loss: float         # positive number
    breakeven: list[float]
    net_debit: float        # positive => debit; negative => credit (price units)


def _leg_intrinsic(leg: TradeLeg, S: float) -> float:
    if leg.option_type == OptionType.CALL:
        intr = max(S - leg.strike, 0.0)
    else:
        intr = max(leg.strike - S, 0.0)
    sign = +1 if leg.action == "BUY" else -1
    return sign * leg.quantity * intr


def _leg_premium(leg: TradeLeg) -> float:
    """BUY -> debit positive; SELL -> credit negative (i.e., we receive cash)."""
    sign = +1 if leg.action == "BUY" else -1
    return sign * leg.quantity * leg.premium


def net_debit(legs: list[TradeLeg]) -> float:
    return sum(_leg_premium(l) for l in legs)


def payoff_at(legs: list[TradeLeg], S: float) -> float:
    """P/L at expiration (price units, per-contract before multiplier)."""
    nd = net_debit(legs)
    intrinsic_total = sum(_leg_intrinsic(l, S) for l in legs)
    return intrinsic_total - nd


def vertical_spread_metrics(legs: list[TradeLeg]) -> PayoffResult:
    """For 2-leg vertical debit/credit spreads (same expiration, same option_type)."""
    if len(legs) != 2:
        raise ValueError("vertical_spread_metrics requires exactly 2 legs")
    if legs[0].option_type != legs[1].option_type:
        raise ValueError("vertical legs must share option_type")
    if legs[0].expiration != legs[1].expiration:
        raise ValueError("vertical legs must share expiration")

    nd = net_debit(legs)
    long_leg = next((l for l in legs if l.action == "BUY"), None)
    short_leg = next((l for l in legs if l.action == "SELL"), None)
    if long_leg is None or short_leg is None:
        raise ValueError("vertical must have one BUY and one SELL")

    width = abs(long_leg.strike - short_leg.strike)
    is_debit = nd > 0

    if is_debit:
        max_loss = nd                            # premium paid
        max_profit = max(width - nd, 0.0)
    else:
        credit = -nd
        max_loss = max(width - credit, 0.0)
        max_profit = credit

    # breakeven
    if long_leg.option_type == OptionType.CALL:
        if is_debit:                             # bull call spread
            be = long_leg.strike + nd
        else:                                    # bear/short call spread
            be = short_leg.strike + (-nd)
    else:
        if is_debit:                             # bear put spread
            be = long_leg.strike - nd
        else:                                    # bull/short put spread
            be = short_leg.strike - (-nd)

    return PayoffResult(max_profit=max_profit, max_loss=max_loss, breakeven=[be], net_debit=nd)


def single_long_metrics(leg: TradeLeg) -> PayoffResult:
    if leg.action != "BUY":
        raise ValueError("YOLO must be a BUY leg")
    nd = _leg_premium(leg)                       # debit
    if leg.option_type == OptionType.CALL:
        be = leg.strike + leg.premium
    else:
        be = leg.strike - leg.premium
    return PayoffResult(
        max_profit=float("inf") if leg.option_type == OptionType.CALL else (leg.strike - leg.premium),
        max_loss=nd,
        breakeven=[be],
        net_debit=nd,
    )


def metrics_for_structure(structure: SpreadStructure, legs: list[TradeLeg]) -> PayoffResult:
    if structure == SpreadStructure.SINGLE_LONG:
        return single_long_metrics(legs[0])
    if structure in {
        SpreadStructure.BULL_CALL_SPREAD,
        SpreadStructure.BEAR_PUT_SPREAD,
        SpreadStructure.PUT_DEBIT_SPREAD,
        SpreadStructure.CALL_DEBIT_SPREAD,
        SpreadStructure.CALL_CREDIT_SPREAD,
        SpreadStructure.PUT_CREDIT_SPREAD,
    }:
        return vertical_spread_metrics(legs)
    if structure == SpreadStructure.RATIO:
        # Only allowed if max_loss is finitely bounded — caller must verify and
        # then construct a custom PayoffResult. We refuse to default-compute here.
        raise NotImplementedError("ratio spreads must be computed by the caller with bounded-loss proof")
    if structure == SpreadStructure.CALENDAR:
        raise NotImplementedError("calendar spreads require term-structure pricing; not computed at expiration")
    raise ValueError(f"unknown structure {structure}")
