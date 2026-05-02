"""Ingest orchestration. Wraps each vendor module with audit logging."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from app.storage.repository import finish_ingest_run, start_ingest_run

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    vendor: str
    status: str
    rows_added: int = 0
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    completed_at: datetime | None = None


def run_one(vendor: str, fn: Callable[..., int], **kwargs) -> IngestResult:
    """Run a single ingest function with audit + error capture."""
    run_id = start_ingest_run(vendor)
    res = IngestResult(vendor=vendor, status="running")
    try:
        rows = fn(**kwargs)
        res.rows_added = int(rows or 0)
        res.status = "success"
    except Exception as e:
        log.warning("%s ingest failed: %s", vendor, e)
        res.status = "failed"
        res.error = str(e)
    finally:
        res.completed_at = datetime.now(tz=timezone.utc)
        finish_ingest_run(run_id, rows_added=res.rows_added,
                          status=res.status, error_message=res.error)
    return res


def run_all(*, lookback_hours: int = 24,
            include_chains: bool = False,
            chain_roots: list[str] | None = None,
            chain_expiration: str | None = None) -> list[IngestResult]:
    """Run every ingest job. Chains are opt-in (require IB Gateway running)."""
    from app.ingest import fred, gdelt, newsapi, rss

    results: list[IngestResult] = []
    results.append(run_one("gdelt", gdelt.ingest, lookback_hours=lookback_hours))
    results.append(run_one("newsapi", newsapi.ingest, lookback_hours=lookback_hours))
    results.append(run_one("rss", rss.ingest, lookback_hours=lookback_hours))
    results.append(run_one("fred", fred.ingest))

    if include_chains:
        from app.ingest import ibkr_chain
        roots = chain_roots or ["ZN", "ES"]
        for r in roots:
            results.append(run_one(
                f"ibkr:{r}",
                ibkr_chain.ingest,
                root=r,
                expiration=chain_expiration,
            ))
    return results
