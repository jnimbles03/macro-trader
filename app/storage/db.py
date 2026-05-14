"""Database engine — SQLite for dev, Postgres/TimescaleDB for prod.

Priority:
1. DB_URL environment variable (set in docker-compose)
2. db_url setting from .env file (pydantic-settings)
3. db_path SQLite fallback
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import REPO_ROOT, get_settings


def _engine_url() -> str:
    # 1. Direct env var (docker-compose sets this)
    db_url = os.environ.get("DB_URL", "")
    if db_url:
        return db_url

    # 2. Pydantic settings (from .env file)
    s = get_settings()
    if s.db_url:
        return s.db_url

    # 3. SQLite fallback
    p = s.db_path
    if not p.startswith("sqlite"):
        path = Path(p)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"
    return p


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "")
    if url:
        return url
    return get_settings().redis_url


def make_engine():
    url = _engine_url()
    if url.startswith("postgresql"):
        return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10, future=True)
    return create_engine(url, future=True)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, future=True, bind=make_engine())
