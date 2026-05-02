"""Schema bootstrap. Postgres-compatible DDL kept minimal."""

from __future__ import annotations

from sqlalchemy import text

from app.storage.db import make_engine


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id TEXT PRIMARY KEY,
    trade_idea_json TEXT NOT NULL,
    opened_at TIMESTAMP NOT NULL,
    closed_at TIMESTAMP,
    status TEXT NOT NULL,
    pnl REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at TIMESTAMP NOT NULL,
    regime TEXT,
    persona_weights TEXT,
    spread_summary TEXT,
    yolo_summary TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS headlines_seen (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    tier TEXT NOT NULL,
    published_at TIMESTAMP NOT NULL,
    category TEXT,
    seen_at TIMESTAMP NOT NULL
);
"""


def init_schema() -> None:
    eng = make_engine()
    with eng.begin() as conn:
        for stmt in SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            conn.execute(text(stmt))
