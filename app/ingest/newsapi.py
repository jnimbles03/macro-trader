"""NewsAPI ingest.

Free Developer tier excludes paywalled publishers (WSJ/FT/Bloomberg/Nikkei),
so we do NOT use a domain whitelist. Phrase-quoted query keeps results macro.
Free tier limits articles older than 30 days.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.models.headline import CredibilityTier
from app.storage.repository import upsert_headlines

log = logging.getLogger(__name__)

VENDOR = "newsapi"

_QUERY = (
    '"Federal Reserve" OR "FOMC" OR "ECB" OR "OPEC" OR '
    '"yield curve" OR "rate cut" OR "rate hike" OR "core PCE"'
)


def ingest(*, lookback_hours: int = 24,
           since: datetime | None = None,
           until: datetime | None = None) -> int:
    s = get_settings()
    if not s.newsapi_key:
        return 0

    if since is None:
        since = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    if until is None:
        until = datetime.now(tz=timezone.utc)

    rows = _fetch(s.newsapi_key, since, until)
    return upsert_headlines(rows, VENDOR)


def _fetch(key: str, since: datetime, until: datetime) -> list[dict]:
    url = "https://newsapi.org/v2/everything"
    # NOTE: free Developer tier has a ~24h article delay — passing `from`/`to`
    # restricted to the last 24h returns 0 results. We let NewsAPI default the
    # window (broadest the plan allows) and grab the 100 most recent articles;
    # the orchestrator filters by `published_at >= since` downstream.
    params = {
        "q": _QUERY,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 100,
    }
    headers = {"X-Api-Key": key}
    with httpx.Client(timeout=20.0) as c:
        r = c.get(url, params=params, headers=headers)
        if r.status_code >= 400:
            # NewsAPI puts the real error in the body; surface it.
            raise RuntimeError(f"NewsAPI {r.status_code}: {r.text[:500]}")
        data = r.json()

    out: list[dict] = []
    for art in data.get("articles", []):
        try:
            ts = datetime.fromisoformat(art["publishedAt"].replace("Z", "+00:00"))
            src_name = (art.get("source") or {}).get("name", "NewsAPI")
            tier = _tier_from_source_name(src_name)
            out.append({
                "title": (art.get("title") or "")[:600],
                "source": src_name,
                "tier": tier,
                "published_at": ts,
                "url": art.get("url") or "",
                "summary": art.get("description"),
            })
        except Exception:
            continue
    return out


def _tier_from_source_name(name: str) -> CredibilityTier:
    n = (name or "").lower()
    if any(s in n for s in ("federal reserve", "treasury", "bls", "bea", "eia",
                             "reuters", "associated press", " ap ")):
        return CredibilityTier.TIER_1
    if any(s in n for s in ("financial times", "wall street journal", "bloomberg",
                             "nikkei", "politico", "economist")):
        return CredibilityTier.TIER_2
    if any(s in n for s in ("reddit", "twitter", "x.com", "medium")):
        return CredibilityTier.TIER_4
    return CredibilityTier.TIER_3
