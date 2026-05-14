"""Schema bootstrap. Postgres/TimescaleDB + SQLite compatible DDL."""

from __future__ import annotations

from sqlalchemy import text

from app.storage.db import make_engine, _engine_url


def _pk() -> str:
    return "SERIAL PRIMARY KEY" if _engine_url().startswith("postgresql") else "INTEGER PRIMARY KEY"


SCHEMA_TEMPLATE = """
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
    id {pk},
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

CREATE TABLE IF NOT EXISTS headlines (
    id {pk},
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    tier TEXT NOT NULL,
    published_at TIMESTAMP NOT NULL,
    country TEXT,
    region TEXT,
    category TEXT,
    summary TEXT,
    is_rumor INTEGER DEFAULT 0,
    is_unsourced INTEGER DEFAULT 0,
    vendor TEXT NOT NULL,
    ingested_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_headlines_published ON headlines(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_headlines_category ON headlines(category);
CREATE INDEX IF NOT EXISTS idx_headlines_vendor ON headlines(vendor, ingested_at DESC);

CREATE TABLE IF NOT EXISTS macro_signals (
    id {pk},
    series_id TEXT NOT NULL,
    label TEXT NOT NULL,
    value REAL NOT NULL,
    as_of TIMESTAMP NOT NULL,
    units TEXT,
    vendor TEXT NOT NULL DEFAULT 'fred',
    ingested_at TIMESTAMP NOT NULL,
    UNIQUE(series_id, as_of)
);
CREATE INDEX IF NOT EXISTS idx_macro_series ON macro_signals(series_id, as_of DESC);

CREATE TABLE IF NOT EXISTS option_chains (
    id {pk},
    root TEXT NOT NULL,
    underlying_symbol TEXT NOT NULL,
    underlying_price REAL NOT NULL,
    expiration TEXT NOT NULL,
    quote_time TIMESTAMP NOT NULL,
    multiplier REAL NOT NULL,
    risk_free_rate REAL DEFAULT 0.05,
    tick_size REAL DEFAULT 0.01,
    vendor TEXT NOT NULL DEFAULT 'ibkr',
    ingested_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chains_root_exp ON option_chains(root, expiration, quote_time DESC);

CREATE TABLE IF NOT EXISTS option_contracts (
    id {pk},
    chain_id INTEGER NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL NOT NULL,
    bid REAL,
    ask REAL,
    last REAL,
    iv REAL,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    volume INTEGER DEFAULT 0,
    open_interest INTEGER DEFAULT 0,
    FOREIGN KEY (chain_id) REFERENCES option_chains(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_contracts_chain ON option_contracts(chain_id);
CREATE INDEX IF NOT EXISTS idx_contracts_strike ON option_contracts(chain_id, strike, option_type);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id {pk},
    vendor TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    rows_added INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingest_vendor ON ingest_runs(vendor, started_at DESC);

CREATE TABLE IF NOT EXISTS watchlist (
    id {pk},
    ticker TEXT NOT NULL,
    sec_type TEXT NOT NULL DEFAULT 'STK',
    expiry TEXT,
    requested_by TEXT,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    UNIQUE(ticker, sec_type)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_expires ON watchlist(expires_at);
"""


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines()
                     if not line.lstrip().startswith("--"))


def init_schema() -> None:
    eng = make_engine()
    sql = SCHEMA_TEMPLATE.format(pk=_pk())
    cleaned = _strip_sql_comments(sql)
    with eng.begin() as conn:
        for stmt in cleaned.strip().split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            conn.execute(text(stmt))
    if _engine_url().startswith("postgresql"):
        _maybe_create_hypertable(eng)


def _maybe_create_hypertable(eng) -> None:
    try:
        with eng.begin() as conn:
            result = conn.execute(text(
                "SELECT 1 FROM timescaledb_information.hypertables "
                "WHERE hypertable_name = 'option_chains'"
            )).fetchone()
            if not result:
                conn.execute(text(
                    "SELECT create_hypertable('option_chains', 'ingested_at', "
                    "if_not_exists => TRUE)"
                ))
    except Exception:
        pass
