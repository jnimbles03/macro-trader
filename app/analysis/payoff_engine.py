"""Payoff math for verticals, calendars, ratios, and single longs.

Calendar metrics are computed at the *front* expiration date:
- front legs are settled at intrinsic value
- back legs are marked with Black-76 using their residual time
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.analysis.option_pricing import black76
from app.models.option_contract import OptionType
from app.models.trade_idea import SpreadStructure, TradeLeg

EPS = 1e-9


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


def _tail_slope_same_exp(legs: list[TradeLeg]) -> float:
    """Asymptotic d(payoff)/dS for S -> +inf at common expiration."""
    slope = 0.0
    for leg in legs:
        if leg.option_type == OptionType.CALL:
            sign = +1 if leg.action == "BUY" else -1
            slope += sign * leg.quantity
    return slope


def _slope_same_exp(legs: list[TradeLeg], S: float) -> float:
    """Piecewise slope d(payoff)/dS away from strike kinks."""
    slope = 0.0
    for leg in legs:
        sign = +1 if leg.action == "BUY" else -1
        if leg.option_type == OptionType.CALL and S > leg.strike + EPS:
            slope += sign * leg.quantity
        if leg.option_type == OptionType.PUT and S < leg.strike - EPS:
            slope -= sign * leg.quantity
    return slope


def _unique_sorted_strikes(legs: list[TradeLeg]) -> list[float]:
    return sorted({float(l.strike) for l in legs})


def _breakevens_same_exp(legs: list[TradeLeg]) -> list[float]:
    strikes = _unique_sorted_strikes(legs)
    boundaries = sorted({0.0, *strikes})
    roots: list[float] = []

    for x in boundaries:
        y = payoff_at(legs, x)
        if abs(y) <= EPS:
            roots.append(x)

    for i in range(len(boundaries) - 1):
        a, b = boundaries[i], boundaries[i + 1]
        mid = 0.5 * (a + b)
        slope = _slope_same_exp(legs, mid)
        if abs(slope) <= EPS:
            continue
        ya = payoff_at(legs, a)
        root = a - ya / slope
        if a + EPS < root < b - EPS:
            roots.append(root)

    high_start = max(boundaries)
    high_slope = _tail_slope_same_exp(legs)
    if abs(high_slope) > EPS:
        y0 = payoff_at(legs, high_start)
        root = high_start - y0 / high_slope
        if root > high_start + EPS:
            roots.append(root)

    deduped: list[float] = []
    for root in sorted(roots):
        if not deduped or abs(root - deduped[-1]) > 1e-6:
            deduped.append(root)
    return deduped


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


def ratio_spread_metrics(legs: list[TradeLeg]) -> PayoffResult:
    """Metrics for same-expiration ratio structures.

    Supports arbitrary quantities and computes payoff exactly at expiration.
    """
    if len(legs) < 2:
        raise ValueError("ratio_spread_metrics requires at least 2 legs")
    if len({l.expiration for l in legs}) != 1:
        raise ValueError("ratio legs must share expiration")
    if len({l.option_type for l in legs}) != 1:
        raise ValueError("ratio legs must share option_type")

    buys = [l for l in legs if l.action == "BUY"]
    sells = [l for l in legs if l.action == "SELL"]
    if not buys or not sells:
        raise ValueError("ratio structure must include both BUY and SELL legs")

    nd = net_debit(legs)
    eval_points = sorted({0.0, *[l.strike for l in legs]})
    pnl_points = [payoff_at(legs, S) for S in eval_points]

    finite_max_profit = max(max(pnl_points), 0.0)
    finite_max_loss = max(-min(pnl_points), 0.0)

    high_slope = _tail_slope_same_exp(legs)
    max_profit = float("inf") if high_slope > EPS else finite_max_profit
    max_loss = float("inf") if high_slope < -EPS else finite_max_loss

    return PayoffResult(
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=_breakevens_same_exp(legs),
        net_debit=nd,
    )


def _residual_years(anchor_expiration, leg_expiration) -> float:
    return max((leg_expiration - anchor_expiration).days / 365.25, 1e-6)


def _calendar_value_at_front_expiration(
    legs: list[TradeLeg],
    S: float,
    *,
    front_expiration,
    risk_free_rate: float,
) -> float:
    terminal_value = 0.0
    for leg in legs:
        sign = +1 if leg.action == "BUY" else -1
        if leg.expiration <= front_expiration:
            if leg.option_type == OptionType.CALL:
                intr = max(S - leg.strike, 0.0)
            else:
                intr = max(leg.strike - S, 0.0)
            terminal_value += sign * leg.quantity * intr
            continue

        residual_t = _residual_years(front_expiration, leg.expiration)
        sigma = max(leg.iv, 1e-6)
        theo = black76(
            F=max(S, 1e-9),
            K=leg.strike,
            sigma=sigma,
            T=residual_t,
            r=risk_free_rate,
            option_type=leg.option_type,
        ).price
        terminal_value += sign * leg.quantity * theo

    return terminal_value - net_debit(legs)


def _calendar_call_tail_slope(
    legs: list[TradeLeg],
    *,
    front_expiration,
    risk_free_rate: float,
) -> float:
    slope = 0.0
    for leg in legs:
        if leg.option_type != OptionType.CALL:
            continue
        sign = +1 if leg.action == "BUY" else -1
        if leg.expiration <= front_expiration:
            slope += sign * leg.quantity
        else:
            t = _residual_years(front_expiration, leg.expiration)
            slope += sign * leg.quantity * math.exp(-risk_free_rate * t)
    return slope


def _breakevens_from_grid(xs: list[float], ys: list[float]) -> list[float]:
    roots: list[float] = []
    for i in range(len(xs) - 1):
        x1, x2 = xs[i], xs[i + 1]
        y1, y2 = ys[i], ys[i + 1]

        if abs(y1) <= 1e-6:
            roots.append(x1)
        if y1 * y2 < 0:
            root = x1 + (0.0 - y1) * (x2 - x1) / (y2 - y1)
            roots.append(root)

    if abs(ys[-1]) <= 1e-6:
        roots.append(xs[-1])

    deduped: list[float] = []
    for r in sorted(roots):
        if not deduped or abs(r - deduped[-1]) > 1e-4:
            deduped.append(r)
    return deduped


def calendar_spread_metrics(legs: list[TradeLeg], *, risk_free_rate: float = 0.05) -> PayoffResult:
    """Metrics for classic calendar spreads at the front expiration.

    Requires one front leg and one or more back legs with the same strike/type.
    """
    if len(legs) < 2:
        raise ValueError("calendar_spread_metrics requires at least 2 legs")
    if len({l.option_type for l in legs}) != 1:
        raise ValueError("calendar legs must share option_type")
    if len({l.strike for l in legs}) != 1:
        raise ValueError("calendar legs must share strike")

    expirations = sorted({l.expiration for l in legs})
    if len(expirations) < 2:
        raise ValueError("calendar legs must span at least 2 expirations")
    front_expiration = expirations[0]

    front_legs = [l for l in legs if l.expiration == front_expiration]
    back_legs = [l for l in legs if l.expiration > front_expiration]
    if not front_legs or not back_legs:
        raise ValueError("calendar must include both front and back legs")

    nd = net_debit(legs)

    base_strike = max(front_legs[0].strike, 1.0)
    s_max = max(base_strike * 3.0, base_strike + 200.0)
    points = 801
    xs = [i * s_max / (points - 1) for i in range(points)]
    ys = [
        _calendar_value_at_front_expiration(
            legs,
            S,
            front_expiration=front_expiration,
            risk_free_rate=risk_free_rate,
        )
        for S in xs
    ]

    finite_max_profit = max(max(ys), 0.0)
    finite_max_loss = max(-min(ys), 0.0)

    tail_slope = _calendar_call_tail_slope(
        legs,
        front_expiration=front_expiration,
        risk_free_rate=risk_free_rate,
    )

    max_profit = float("inf") if tail_slope > EPS else finite_max_profit
    max_loss = float("inf") if tail_slope < -EPS else finite_max_loss

    return PayoffResult(
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=_breakevens_from_grid(xs, ys),
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
        return ratio_spread_metrics(legs)
    if structure == SpreadStructure.CALENDAR:
        return calendar_spread_metrics(legs)
    raise ValueError(f"unknown structure {structure}")
