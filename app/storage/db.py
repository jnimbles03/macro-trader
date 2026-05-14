"""Database engine helper — supports SQLite (dev) and Postgres (prod)."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import REPO_ROOT, get_settings


def _engine_url() -> str:
    # Postgres takes priority if DB_URL is set and looks like postgres
    db_url = os.getenv("DB_URL", "") or os.getenv("DATABASE_URL", "")
    if db_url.startswith("postgresql") or db_url.startswith("postgres"):
        return db_url

    # Fall back to SQLite path from settings
    s = get_settings()
    p = s.db_path
    if not p.startswith("sqlite"):
        path = Path(p)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"
    return p


def make_engine():
    url = _engine_url()
    if url.startswith("sqlite"):
        return create_engine(url, future=True)
    # Postgres — use psycopg2, pool_pre_ping for reconnect resilience
    return create_engine(url, future=True, pool_pre_ping=True)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, future=True, bind=make_engine())
