"""Trade idea + leg + validator verdict models."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.option_contract import OptionType


class TradeKind(str, Enum):
    DEFINED_RISK_SPREAD = "defined_risk_spread"
    YOLO_LONG = "yolo_long"


class SpreadStructure(str, Enum):
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    PUT_DEBIT_SPREAD = "put_debit_spread"
    CALL_DEBIT_SPREAD = "call_debit_spread"
    CALL_CREDIT_SPREAD = "call_credit_spread"
    PUT_CREDIT_SPREAD = "put_credit_spread"
    CALENDAR = "calendar"
    RATIO = "ratio"
    SINGLE_LONG = "single_long"


class TradeLeg(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: Literal["BUY", "SELL"]
    quantity: int = Field(..., ge=1)
    option_type: OptionType
    strike: float
    expiration: date
    premium: float                  # debit positive, credit positive (sign carried in action)
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float


class NoTradeReason(str, Enum):
    WEAK_SIGNAL = "weak_signal"
    CONFLICTING_PERSONAS = "conflicting_personas"
    MISSING_CHAIN_DATA = "missing_chain_data"
    STALE_QUOTES = "stale_quotes"
    WIDE_MARKETS = "wide_markets"
    NO_CLEAN_EXPRESSION = "no_clean_expression"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"
    RR_BELOW_FLOOR = "rr_below_floor"
    NAKED_SHORT_REJECTED = "naked_short_rejected"
    UNCAPPED_RISK = "uncapped_risk"
    VALIDATOR_REJECTED = "validator_rejected"
    UNSUPPORTED_ROOT = "unsupported_root"
    REGIME_NO_SIGNAL = "regime_no_signal"


class ValidatorVerdict(BaseModel):
    """Opus's adversarial review of a Grok-generated trade."""
    decision: Literal["accept", "revise", "reject"]
    news_check: str                          # plausibility of cited headlines
    trade_theory_check: str                  # coherence of causal chain
    risk_reward_check: str                   # 2:1 floor truly cleared, math sane
    option_strategy_check: str               # structure expresses thesis cleanly
    issues: list[str] = Field(default_factory=list)
    revisions_suggested: list[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0, le=1)


class TradeIdea(BaseModel):
    """The full trade card with risk math + validator output."""

    kind: TradeKind
    name: str
    root: str
    underlying_symbol: str
    direction: Literal["bullish", "bearish", "neutral", "long_vol", "short_vol"]
    structure: SpreadStructure
    expiration: date
    legs: list[TradeLeg]

    entry_debit_credit: float       # positive = debit; negative = credit
    max_loss: float                  # always positive dollars per spread
    max_profit: float                # always positive dollars per spread (or "inf" → use big number)
    breakeven: list[float]
    rr_ratio: float                  # max_profit / max_loss
    expected_move_pct: float | None = None
    probability_itm: float | None = None     # only when chain quality is high

    # liquidity / quality flags
    bid_ask_pct_worst: float
    min_volume: int
    min_open_interest: int

    # narrative
    catalyst: str
    causal_chain: str
    why_this_structure: str
    what_kills_thesis: str
    why_probably_dumb: str | None = None      # required for YOLO
    invalidation: str
    stop_logic: str
    profit_taking_logic: str

    # sizing
    suggested_contracts: int | None = None
    risk_dollars: float | None = None
    sizing_note: str | None = None

    # provenance
    cluster_names: list[str] = Field(default_factory=list)
    persona_attribution: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    model_primary: str = ""
    validator_model: str = ""
    validator_verdict: ValidatorVerdict | None = None

    # === guards ===
    @model_validator(mode="after")
    def _validate(self):
        # Naked short rejected universally.
        if self.kind == TradeKind.YOLO_LONG:
            if self.structure != SpreadStructure.SINGLE_LONG:
                raise ValueError("YOLO trades must be single_long")
            if len(self.legs) != 1 or self.legs[0].action != "BUY":
                raise ValueError("YOLO must be exactly one long option (no naked shorts)")
            if self.why_probably_dumb is None or not self.why_probably_dumb.strip():
                raise ValueError("YOLO must include 'why this is probably dumb'")
        else:
            # Defined-risk: every short leg must be paired with a long leg of the same type
            # (no naked shorts permitted) and max_loss must be finite.
            buys = [l for l in self.legs if l.action == "BUY"]
            sells = [l for l in self.legs if l.action == "SELL"]
            if sells and not buys:
                raise ValueError("naked short rejected: short legs require offsetting long protection")
            for s in sells:
                # Must have at least one long leg of the same option_type providing cap.
                same_type_longs = [l for l in buys if l.option_type == s.option_type]
                if not same_type_longs:
                    raise ValueError(f"naked short rejected: short {s.option_type.value} has no long protection")
            if self.max_loss <= 0:
                raise ValueError("max_loss must be positive (defined-risk)")
            if not (self.max_loss < 1e9):
                raise ValueError("max_loss is not bounded — uncapped risk rejected")

            # Hard 2:1 floor.
            if self.rr_ratio < 2.0 - 1e-9:
                raise ValueError(f"defined-risk spread rr_ratio {self.rr_ratio:.2f} < 2.0 floor")

        return self


class NoTrade(BaseModel):
    """A NO TRADE response for a slot."""
    slot: Literal["spread", "yolo"]
    reason: NoTradeReason
    detail: str = ""


# Marker used in trade_selector return
NO_TRADE = "NO_TRADE"
