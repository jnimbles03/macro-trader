"""Headline + cluster models with strict credibility tiers."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class CredibilityTier(str, Enum):
    TIER_1 = "tier_1"  # 0.90–1.00 — central banks, Treasury, BLS/BEA/EIA, IMF, Reuters/AP wire
    TIER_2 = "tier_2"  # 0.75–0.90 — FT, WSJ, Bloomberg, Nikkei, Politico
    TIER_3 = "tier_3"  # 0.50–0.75 — trade press, sector outlets
    TIER_4 = "tier_4"  # 0.20–0.50 — blogs, social, anonymous

    @property
    def floor(self) -> float:
        return {self.TIER_1: 0.90, self.TIER_2: 0.75, self.TIER_3: 0.50, self.TIER_4: 0.20}[self]

    @property
    def midpoint(self) -> float:
        return {self.TIER_1: 0.95, self.TIER_2: 0.825, self.TIER_3: 0.625, self.TIER_4: 0.35}[self]


MacroChannel = Literal[
    "monetary_policy",
    "fiscal",
    "treasury_issuance",
    "inflation",
    "labor_growth",
    "central_bank_communication",
    "credit_stress",
    "banking_liquidity",
    "geopolitical_risk",
    "energy_commodities",
    "china",
    "europe",
    "japan",
    "elections_regulation",
    "tariffs_sanctions",
    "market_plumbing_volatility",
    "positioning",
    "other",
]


class Headline(BaseModel):
    """A single headline. Never fabricated — always sourced."""

    model_config = ConfigDict(frozen=True)

    title: str
    source: str
    tier: CredibilityTier
    published_at: datetime
    url: HttpUrl | str
    country: str | None = None
    region: str | None = None
    category: MacroChannel = "other"
    summary: str | None = None
    is_rumor: bool = False
    is_unsourced: bool = False

    @field_validator("title", "source")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must be non-empty")
        return v


class HeadlineCluster(BaseModel):
    """A deduped cluster of related headlines."""

    name: str
    channel: MacroChannel
    headlines: list[Headline] = Field(default_factory=list)
    market_relevance: float = 0.0      # 0..1
    policy_relevance: float = 0.0
    surprise_factor: float = 0.0
    cross_asset_impact: float = 0.0
    time_sensitivity: float = 0.0
    vol_potential: float = 0.0
    summary: str = ""
    countries: list[str] = Field(default_factory=list)

    @property
    def best_tier(self) -> CredibilityTier:
        if not self.headlines:
            return CredibilityTier.TIER_4
        return min((h.tier for h in self.headlines), key=lambda t: ["tier_1", "tier_2", "tier_3", "tier_4"].index(t.value))

    @property
    def credibility_weight(self) -> float:
        return self.best_tier.midpoint

    @property
    def composite_score(self) -> float:
        # Weighted aggregate; credibility is a multiplier — Tier 4 gets heavily attenuated.
        base = (
            0.20 * self.market_relevance
            + 0.15 * self.policy_relevance
            + 0.20 * self.surprise_factor
            + 0.15 * self.cross_asset_impact
            + 0.15 * self.time_sensitivity
            + 0.15 * self.vol_potential
        )
        return round(base * self.credibility_weight, 4)
