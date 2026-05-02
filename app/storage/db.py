"""SQLite engine + session helper."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import REPO_ROOT, get_settings


def _engine_url() -> str:
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
    return create_engine(_engine_url(), future=True)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, future=True, bind=make_engine())
