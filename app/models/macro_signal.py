"""Macro signals (FRED data points + regime assessment)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Regime(str, Enum):
    LIQUIDITY_EXPANSION = "liquidity_expansion"
    LIQUIDITY_WITHDRAWAL = "liquidity_withdrawal"
    INFLATION_SCARE = "inflation_scare"
    GROWTH_SCARE = "growth_scare"
    POLICY_MISTAKE = "policy_mistake"
    CREDIT_STRESS = "credit_stress"
    GEOPOLITICAL_SHOCK = "geopolitical_shock"
    RISK_ON_MELTUP = "risk_on_meltup"
    RISK_OFF_DELEVERAGING = "risk_off_deleveraging"
    NO_SIGNAL = "no_signal"           # range-bound — valid output, triggers NO TRADE on both slots
    CONFLICTED = "conflicted"


class MacroSignal(BaseModel):
    """A single macro datapoint, e.g. FRED series."""
    series_id: str
    label: str
    value: float
    as_of: datetime
    units: str | None = None
    surprise_vs_consensus: float | None = None  # Z-score or pct delta if available


class RegimeAssessment(BaseModel):
    """Output of the regime detector."""
    regime: Regime
    confidence: float = Field(..., ge=0, le=1)
    explanation: str
    signals: list[MacroSignal] = Field(default_factory=list)
    persona_weights: dict[str, float] = Field(default_factory=dict)  # name -> 0..1 relevance
    convergence: list[str] = Field(default_factory=list)             # names of personas converging
    dissent: list[str] = Field(default_factory=list)
