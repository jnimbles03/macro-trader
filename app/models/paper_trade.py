"""Paper trade log entries."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PaperTradeStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"
    CANCELED = "canceled"


class PaperTrade(BaseModel):
    id: str
    trade_idea_json: str
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None
    status: PaperTradeStatus = PaperTradeStatus.OPEN
    pnl: float | None = None
    notes: str | None = None
