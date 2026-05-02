"""GDELT 2.0 Doc API ingest.

Theme + domain filtered to macro-grade sources. GDELT free tier is rate
limited; on 429 we return 0 rather than crash. Supports backfill via
explicit `since`/`until` (uses GDELT's STARTDATETIME/ENDDATETIME params).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.models.headline import CredibilityTier
from app.storage.repository import upsert_headlines

log = logging.getLogger(__name__)

VENDOR = "gdelt"

_DOMAINS = (
    "domain:reuters.com OR domain:apnews.com OR domain:ft.com OR domain:wsj.com "
    "OR domain:bloomberg.com OR domain:cnbc.com OR domain:marketwatch.com "
    "OR domain:economist.com OR domain:nikkei.com OR domain:politico.com"
)
_THEMES = (
    "theme:ECON_INTEREST_RATES OR theme:ECON_INFLATION OR theme:ECON_CENTRAL_BANK "
    "OR theme:ECON_DEBT OR theme:ECON_TRADE_DEAL OR theme:ECON_BANK_DEBT "
    "OR theme:ECON_BANKRUPTCY OR theme:ECON_STIMULUS OR theme:ECON_MONOPOLY"
)


def ingest(*, lookback_hours: int = 24,
           since: datetime | None = None,
           until: datetime | None = None) -> int:
    s = get_settings()
    if not s.gdelt_enabled:
        return 0

    if since is not None:
        return _ingest_window(since, until or datetime.now(tz=timezone.utc))

    return _ingest_recent(lookback_hours)


def _ingest_recent(lookback_hours: int) -> int:
    rows = _fetch_window(timespan_hours=lookback_hours)
    return upsert_headlines(rows, VENDOR)


def _ingest_window(since: datetime, until: datetime) -> int:
    """Backfill: chunk into 24h windows (GDELT prefers smaller queries)."""
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    total = 0
    cursor = since
    while cursor < until:
        chunk_end = min(cursor + timedelta(hours=24), until)
        rows = _fetch_window(start=cursor, end=chunk_end)
        total += upsert_headlines(rows, VENDOR)
        cursor = chunk_end
    return total


def _fetch_window(*, timespan_hours: int | None = None,
                  start: datetime | None = None,
                  end: datetime | None = None) -> list[dict]:
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": f"({_DOMAINS}) AND ({_THEMES}) sourcelang:eng",
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 100,
        "sort": "datedesc",
    }
    if timespan_hours is not None:
        params["timespan"] = f"{timespan_hours}h"
    if start is not None:
        params["startdatetime"] = start.strftime("%Y%m%d%H%M%S")
    if end is not None:
        params["enddatetime"] = end.strftime("%Y%m%d%H%M%S")

    try:
        with httpx.Client(timeout=30.0) as c:
            r = c.get(url, params=params)
            if r.status_code == 429:
                log.warning("GDELT 429; skipping")
                return []
            r.raise_for_status()
            if not r.text or not r.text.strip().startswith("{"):
                log.warning("GDELT returned non-JSON body; skipping")
                return []
            data = r.json()
    except Exception as e:
        log.warning("GDELT fetch failed: %s", e)
        return []

    out: list[dict] = []
    for art in data.get("articles", []):
        try:
            ts = datetime.strptime(art["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            domain = art.get("domain", "")
            tier = _tier_from_domain(domain)
            out.append({
                "title": art.get("title", "")[:600],
                "source": domain or "GDELT",
                "tier": tier,
                "published_at": ts,
                "url": art["url"],
                "country": art.get("sourcecountry"),
            })
        except Exception:
            continue
    return out


_TIER_1_DOMAINS = {"reuters.com", "apnews.com"}
_TIER_2_DOMAINS = {"ft.com", "wsj.com", "bloomberg.com", "nikkei.com", "politico.com",
                   "economist.com"}


def _tier_from_domain(domain: str) -> CredibilityTier:
    d = (domain or "").lower()
    if any(d.endswith(t) for t in _TIER_1_DOMAINS):
        return CredibilityTier.TIER_1
    if any(d.endswith(t) for t in _TIER_2_DOMAINS):
        return CredibilityTier.TIER_2
    return CredibilityTier.TIER_3
