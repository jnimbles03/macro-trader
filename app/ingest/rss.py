"""RSS ingest — central banks + statistical agencies + market wires.

No backfill — RSS feeds only carry recent items by definition. The lookback
is just a published_at cutoff applied to whatever the feed currently lists.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.headline import CredibilityTier
from app.storage.repository import upsert_headlines

log = logging.getLogger(__name__)

VENDOR = "rss"

_FEEDS: list[tuple[str, CredibilityTier]] = [
    # Central banks & stat agencies (tier 1)
    ("https://www.federalreserve.gov/feeds/press_all.xml", CredibilityTier.TIER_1),
    ("https://home.treasury.gov/rss/press-releases.xml", CredibilityTier.TIER_1),
    ("https://www.bea.gov/rss.xml", CredibilityTier.TIER_1),
    ("https://www.bls.gov/feed/news_release/empsit.rss", CredibilityTier.TIER_1),
    ("https://www.eia.gov/rss/press_releases.xml", CredibilityTier.TIER_1),
    ("https://www.ecb.europa.eu/rss/press.html", CredibilityTier.TIER_1),
    ("https://feeds.reuters.com/reuters/businessNews", CredibilityTier.TIER_1),
    # Free market wires (tier 3 — broad reliability)
    ("https://feeds.content.dowjones.io/public/rss/mw_topstories", CredibilityTier.TIER_3),
    ("https://finance.yahoo.com/news/rssindex", CredibilityTier.TIER_3),
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html", CredibilityTier.TIER_3),
]


def ingest(*, lookback_hours: int = 24,
           since: datetime | None = None,
           until: datetime | None = None) -> int:
    try:
        import feedparser
    except ImportError:
        log.warning("feedparser not installed; skipping RSS")
        return 0

    cutoff = since if since is not None else datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    end = until if until is not None else datetime.now(tz=timezone.utc) + timedelta(minutes=5)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    rows: list[dict] = []
    for url, tier in _FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            log.warning("RSS %s failed: %s", url, e)
            continue
        for entry in feed.entries[:50]:
            try:
                ts = _parse_rss_time(entry)
                if ts is None or ts < cutoff or ts > end:
                    continue
                rows.append({
                    "title": (entry.get("title") or "")[:600],
                    "source": feed.feed.get("title", url),
                    "tier": tier,
                    "published_at": ts,
                    "url": entry.get("link", url),
                    "summary": entry.get("summary"),
                })
            except Exception:
                continue
    return upsert_headlines(rows, VENDOR)


def _parse_rss_time(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(_time.mktime(parsed), tz=timezone.utc)
