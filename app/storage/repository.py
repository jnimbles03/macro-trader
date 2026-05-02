"""Repository functions over SQLite."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import text

from app.models.paper_trade import PaperTrade, PaperTradeStatus
from app.models.trade_idea import TradeIdea
from app.storage.db import make_engine


def save_paper_trade(idea: TradeIdea, *, notes: str | None = None) -> PaperTrade:
    pt = PaperTrade(
        id=str(uuid.uuid4()),
        trade_idea_json=idea.model_dump_json(),
        opened_at=datetime.utcnow(),
        closed_at=None,
        status=PaperTradeStatus.OPEN,
        pnl=None,
        notes=notes,
    )
    eng = make_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO paper_trades (id, trade_idea_json, opened_at, status, notes)
            VALUES (:id, :j, :opened_at, :status, :notes)
        """), {"id": pt.id, "j": pt.trade_idea_json, "opened_at": pt.opened_at,
                "status": pt.status.value, "notes": pt.notes})
    return pt


def list_paper_trades(limit: int = 50) -> list[PaperTrade]:
    eng = make_engine()
    with eng.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, trade_idea_json, opened_at, closed_at, status, pnl, notes
            FROM paper_trades ORDER BY opened_at DESC LIMIT :limit
        """), {"limit": limit}).fetchall()
    out: list[PaperTrade] = []
    for r in rows:
        out.append(PaperTrade(
            id=r[0],
            trade_idea_json=r[1],
            opened_at=r[2],
            closed_at=r[3],
            status=PaperTradeStatus(r[4]),
            pnl=r[5],
            notes=r[6],
        ))
    return out


def log_run(regime: str, persona_weights: dict, spread_summary: str, yolo_summary: str,
            *, notes: str | None = None) -> None:
    eng = make_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO run_log (ran_at, regime, persona_weights, spread_summary, yolo_summary, notes)
            VALUES (:ran_at, :regime, :pw, :ss, :ys, :notes)
        """), {"ran_at": datetime.utcnow(), "regime": regime,
                "pw": json.dumps(persona_weights), "ss": spread_summary, "ys": yolo_summary,
                "notes": notes})


def remember_headlines(headlines: list[dict]) -> None:
    if not headlines:
        return
    eng = make_engine()
    with eng.begin() as conn:
        for h in headlines:
            conn.execute(text("""
                INSERT OR IGNORE INTO headlines_seen (url, title, source, tier, published_at, category, seen_at)
                VALUES (:url, :title, :source, :tier, :published_at, :category, :seen_at)
            """), {**h, "seen_at": datetime.utcnow()})
