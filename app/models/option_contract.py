"""Option contract + chain models. All fields required — no estimation."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OptionType(str, Enum):
    CALL = "C"
    PUT = "P"


class OptionContract(BaseModel):
    """A single options contract with live-quote inputs.

    All Greek and IV fields must come from data, never estimated. If absent,
    the trade selector returns NO TRADE.
    """
    model_config = ConfigDict(frozen=True)

    root: str                       # e.g. "ZN", "ES"
    underlying_symbol: str           # e.g. "ZNM4"
    underlying_price: float          # futures price (F for Black-76)
    option_type: OptionType
    strike: float
    expiration: date
    multiplier: float                # contract multiplier (e.g. 1000 for ZN, 50 for ES)
    point_value: float | None = None
    bid: float
    ask: float
    last: float | None = None
    mark: float | None = None        # midpoint if not provided
    iv: float                        # implied volatility (decimal)
    delta: float
    gamma: float
    theta: float                     # per-day
    vega: float
    volume: int = 0
    open_interest: int = 0
    quote_time: datetime
    risk_free_rate: float = 0.05      # for Black-76 discounting
    tick_size: float = 0.01

    @field_validator("bid", "ask", "iv", "strike", "underlying_price")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("must be non-negative")
        return v

    @field_validator("ask")
    @classmethod
    def _ask_ge_bid(cls, v: float, info):
        bid = info.data.get("bid")
        if bid is not None and v < bid:
            raise ValueError("ask must be >= bid")
        return v

    @property
    def mid(self) -> float:
        if self.mark is not None:
            return self.mark
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return max(self.ask - self.bid, 0.0)

    @property
    def spread_pct(self) -> float:
        m = self.mid
        return (self.spread / m) if m > 0 else float("inf")

    def time_to_expiry_years(self, now: datetime | None = None) -> float:
        now = now or datetime.utcnow()
        delta = datetime.combine(self.expiration, datetime.min.time()) - now
        return max(delta.total_seconds() / (365.25 * 24 * 3600), 1e-6)


class OptionChain(BaseModel):
    """A snapshot of an option chain for one root/expiration."""
    root: str
    underlying_symbol: str
    underlying_price: float
    expiration: date
    quote_time: datetime
    contracts: list[OptionContract] = Field(default_factory=list)
    multiplier: float

    @property
    def is_stale(self) -> bool:
        # 5-minute staleness window for chains. Compare in UTC, naive-or-aware safe.
        from datetime import timezone
        now = datetime.now(timezone.utc) if self.quote_time.tzinfo else datetime.utcnow()
        return (now - self.quote_time).total_seconds() > 300

    def find(self, strike: float, option_type: OptionType) -> OptionContract | None:
        for c in self.contracts:
            if abs(c.strike - strike) < 1e-6 and c.option_type == option_type:
                return c
        return None
