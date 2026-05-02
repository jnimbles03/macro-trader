"""Risk engine: validates a candidate trade against hard rules.

Returns either the (annotated) TradeIdea or a NoTradeReason.
"""

from __future__ import annotations

from datetime import date

from app.config import SUPPORTED_ROOTS, get_settings
from app.models.option_contract import OptionChain, OptionContract
from app.models.trade_idea import (
    NoTradeReason,
    SpreadStructure,
    TradeIdea,
    TradeKind,
    TradeLeg,
)


class RiskRejection(Exception):
    def __init__(self, reason: NoTradeReason, detail: str = ""):
        super().__init__(detail or reason.value)
        self.reason = reason
        self.detail = detail


def _bid_ask_pct(c: OptionContract) -> float:
    return c.spread_pct


def _check_liquidity(contracts: list[OptionContract], root: str) -> None:
    s = get_settings()
    threshold = s.bid_ask_threshold(root)
    for c in contracts:
        if _bid_ask_pct(c) > threshold + 1e-9:
            raise RiskRejection(NoTradeReason.WIDE_MARKETS,
                                f"{root} bid/ask {c.spread_pct:.3f} > {threshold:.3f}")
        if c.volume < s.min_option_volume:
            raise RiskRejection(NoTradeReason.INSUFFICIENT_LIQUIDITY,
                                f"{root} volume {c.volume} < {s.min_option_volume}")
        if c.open_interest < s.min_open_interest:
            raise RiskRejection(NoTradeReason.INSUFFICIENT_LIQUIDITY,
                                f"{root} OI {c.open_interest} < {s.min_open_interest}")


def _check_root(root: str) -> None:
    if root.upper() not in SUPPORTED_ROOTS:
        raise RiskRejection(NoTradeReason.UNSUPPORTED_ROOT, f"{root} not in supported roots")
    if root.upper() == "VX":
        raise RiskRejection(NoTradeReason.UNSUPPORTED_ROOT,
                            "VX requires special handling (VIX futures); not Black-76 priced")


def _check_chain(chain: OptionChain | None) -> None:
    if chain is None:
        raise RiskRejection(NoTradeReason.MISSING_CHAIN_DATA, "no chain available")
    if chain.is_stale:
        raise RiskRejection(NoTradeReason.STALE_QUOTES, "chain quote_time > 5 min old")
    if not chain.contracts:
        raise RiskRejection(NoTradeReason.MISSING_CHAIN_DATA, "chain has no contracts")


def _check_legs_no_naked_short(legs: list[TradeLeg]) -> None:
    buys = [l for l in legs if l.action == "BUY"]
    sells = [l for l in legs if l.action == "SELL"]
    if sells and not buys:
        raise RiskRejection(NoTradeReason.NAKED_SHORT_REJECTED, "all-short structure rejected")
    for s in sells:
        same_type_longs = [l for l in buys if l.option_type == s.option_type]
        if not same_type_longs:
            raise RiskRejection(NoTradeReason.NAKED_SHORT_REJECTED,
                                f"short {s.option_type.value} has no offsetting long protection")


def _check_0dte(expiration: date) -> None:
    s = get_settings()
    if s.allow_0dte:
        return
    from datetime import datetime
    days = (expiration - datetime.utcnow().date()).days
    if days < 1:
        raise RiskRejection(NoTradeReason.NO_CLEAN_EXPRESSION,
                            "0DTE expiration disallowed (set ALLOW_0DTE=true to override)")


def validate_trade(trade: TradeIdea, chain: OptionChain | None) -> TradeIdea:
    """Run all hard checks. Raises RiskRejection or returns the trade."""
    s = get_settings()

    _check_root(trade.root)
    _check_chain(chain)

    # tie legs back to chain contracts to verify liquidity
    leg_contracts: list[OptionContract] = []
    assert chain is not None
    for leg in trade.legs:
        c = chain.find(leg.strike, leg.option_type)
        if c is None:
            raise RiskRejection(NoTradeReason.MISSING_CHAIN_DATA,
                                f"strike {leg.strike}{leg.option_type.value} not in chain")
        leg_contracts.append(c)

    _check_liquidity(leg_contracts, trade.root)
    _check_legs_no_naked_short(trade.legs)
    _check_0dte(trade.expiration)

    if trade.kind == TradeKind.DEFINED_RISK_SPREAD:
        if trade.rr_ratio < s.min_spread_rr - 1e-9:
            raise RiskRejection(NoTradeReason.RR_BELOW_FLOOR,
                                f"rr_ratio {trade.rr_ratio:.2f} < {s.min_spread_rr}")
        if trade.structure == SpreadStructure.SINGLE_LONG:
            raise RiskRejection(NoTradeReason.NO_CLEAN_EXPRESSION,
                                "single_long not allowed in defined-risk slot")
        if trade.max_loss <= 0 or not (trade.max_loss < 1e9):
            raise RiskRejection(NoTradeReason.UNCAPPED_RISK, "max_loss must be finite & positive")

    if trade.kind == TradeKind.YOLO_LONG:
        if trade.structure != SpreadStructure.SINGLE_LONG:
            raise RiskRejection(NoTradeReason.NO_CLEAN_EXPRESSION,
                                "YOLO must be single_long; spreads cap convexity")
        if len(trade.legs) != 1 or trade.legs[0].action != "BUY":
            raise RiskRejection(NoTradeReason.NAKED_SHORT_REJECTED,
                                "YOLO must be a single long option")
        # bound premium
        premium_dollars = trade.legs[0].premium * chain.multiplier
        if premium_dollars > s.yolo_max_premium_dollars + 1e-6:
            raise RiskRejection(NoTradeReason.NO_CLEAN_EXPRESSION,
                                f"YOLO premium ${premium_dollars:.2f} > cap ${s.yolo_max_premium_dollars:.2f}")

    # set worst bid/ask
    trade = trade.model_copy(update={"bid_ask_pct_worst": max(_bid_ask_pct(c) for c in leg_contracts),
                                     "min_volume": min(c.volume for c in leg_contracts),
                                     "min_open_interest": min(c.open_interest for c in leg_contracts)})
    return trade
