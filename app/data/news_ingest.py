"""Headline ingestion.

Live mode pulls from GDELT (free), NewsAPI (if keyed), and an RSS bundle for
top-tier wires. Mock mode reads `fixtures/headlines_sample.json` so the test
suite + offline runs are deterministic.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.data.cache import cache_key, cached_call
from app.models.headline import CredibilityTier, Headline

log = logging.getLogger(__name__)

# Top-tier wires; extend as needed.
_RSS_FEEDS: list[tuple[str, CredibilityTier]] = [
    ("https://www.federalreserve.gov/feeds/press_all.xml", CredibilityTier.TIER_1),
    ("https://home.treasury.gov/rss/press-releases.xml", CredibilityTier.TIER_1),
    ("https://www.bea.gov/rss.xml", CredibilityTier.TIER_1),
    ("https://www.bls.gov/feed/news_release/empsit.rss", CredibilityTier.TIER_1),
    ("https://www.eia.gov/rss/press_releases.xml", CredibilityTier.TIER_1),
    ("https://www.ecb.europa.eu/rss/press.html", CredibilityTier.TIER_1),
]


def fetch_recent_headlines(*, lookback_hours: int = 24, fresh: bool = False) -> list[Headline]:
    s = get_settings()
    key = cache_key("headlines", lookback_hours, "mock" if s.mock_data else "live")
    return cached_call(
        key,
        ttl_seconds=s.cache_headlines_min * 60,
        fresh=fresh,
        loader=lambda: _load(s, lookback_hours),
    )


def _load(s, lookback_hours: int) -> list[Headline]:
    if s.mock_data:
        return _load_fixture()
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    out: list[Headline] = []
    if s.gdelt_enabled:
        out.extend(_fetch_gdelt(lookback_hours))
    if s.newsapi_key:
        out.extend(_fetch_newsapi(s.newsapi_key, lookback_hours))
    out.extend(_fetch_rss(lookback_hours))
    return [h for h in out if h.published_at >= cutoff]


# ---------------------------------------------------------------------------
# Fixture loader (mock mode)
# ---------------------------------------------------------------------------
def _load_fixture() -> list[Headline]:
    s = get_settings()
    path = s.fixtures_dir / "headlines_sample.json"
    raw = json.loads(path.read_text())
    return [Headline(**h) for h in raw]


# ---------------------------------------------------------------------------
# GDELT (free; no key required)
# Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
# ---------------------------------------------------------------------------
def _fetch_gdelt(lookback_hours: int) -> list[Headline]:
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": '(Federal Reserve OR Treasury OR PCE OR CPI OR ECB OR BOJ OR PBOC OR OPEC OR refunding) sourcelang:eng',
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 75,
        "timespan": f"{lookback_hours}h",
        "sort": "datedesc",
    }
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("GDELT fetch failed: %s", e)
        return []
    out: list[Headline] = []
    for art in data.get("articles", []):
        try:
            ts = datetime.strptime(art["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            domain = art.get("domain", "")
            tier = _tier_from_domain(domain)
            out.append(Headline(
                title=art["title"],
                source=domain or "GDELT",
                tier=tier,
                published_at=ts,
                url=art["url"],
                country=art.get("sourcecountry"),
            ))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# NewsAPI (https://newsapi.org)
# ---------------------------------------------------------------------------
def _fetch_newsapi(key: str, lookback_hours: int) -> list[Headline]:
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": "Federal Reserve OR ECB OR BOJ OR Treasury OR refunding OR OPEC",
        "from": cutoff,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 50,
    }
    headers = {"X-Api-Key": key}
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("NewsAPI fetch failed: %s", e)
        return []
    out: list[Headline] = []
    for art in data.get("articles", []):
        try:
            ts = datetime.fromisoformat(art["publishedAt"].replace("Z", "+00:00"))
            src_name = (art.get("source") or {}).get("name", "NewsAPI")
            tier = _tier_from_source_name(src_name)
            out.append(Headline(
                title=art.get("title") or "",
                source=src_name,
                tier=tier,
                published_at=ts,
                url=art.get("url") or "",
                summary=art.get("description"),
            ))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# RSS — central banks + statistical agencies
# ---------------------------------------------------------------------------
def _fetch_rss(lookback_hours: int) -> list[Headline]:
    try:
        import feedparser
    except ImportError:
        log.warning("feedparser not installed; skipping RSS")
        return []
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    out: list[Headline] = []
    for url, tier in _RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            log.warning("RSS %s failed: %s", url, e)
            continue
        for entry in feed.entries[:25]:
            try:
                ts = _parse_rss_time(entry)
                if ts is None or ts < cutoff:
                    continue
                out.append(Headline(
                    title=entry.get("title", ""),
                    source=feed.feed.get("title", url),
                    tier=tier,
                    published_at=ts,
                    url=entry.get("link", url),
                    summary=entry.get("summary"),
                ))
            except Exception:
                continue
    return out


def _parse_rss_time(entry: Any) -> datetime | None:
    import time as _time
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(_time.mktime(parsed), tz=timezone.utc)


# ---------------------------------------------------------------------------
# Tier inference. Conservative: when in doubt, drop a tier.
# ---------------------------------------------------------------------------
_TIER_1_DOMAINS = {
    "federalreserve.gov", "treasury.gov", "bls.gov", "bea.gov", "eia.gov",
    "ecb.europa.eu", "bankofengland.co.uk", "boj.or.jp", "imf.org",
    "reuters.com", "apnews.com",
}
_TIER_2_DOMAINS = {
    "ft.com", "wsj.com", "bloomberg.com", "nikkei.com", "politico.com",
    "barrons.com", "economist.com",
}
_TIER_4_DOMAINS = {"reddit.com", "x.com", "twitter.com", "medium.com", "substack.com"}


def _tier_from_domain(domain: str) -> CredibilityTier:
    d = (domain or "").lower()
    if any(d.endswith(t) for t in _TIER_1_DOMAINS):
        return CredibilityTier.TIER_1
    if any(d.endswith(t) for t in _TIER_2_DOMAINS):
        return CredibilityTier.TIER_2
    if any(d.endswith(t) for t in _TIER_4_DOMAINS):
        return CredibilityTier.TIER_4
    return CredibilityTier.TIER_3


def _tier_from_source_name(name: str) -> CredibilityTier:
    n = (name or "").lower()
    if any(s in n for s in ("federal reserve", "treasury", "bls", "bea", "eia", "reuters", "associated press")):
        return CredibilityTier.TIER_1
    if any(s in n for s in ("financial times", "wall street journal", "bloomberg", "nikkei", "politico")):
        return CredibilityTier.TIER_2
    if any(s in n for s in ("reddit", "x ", "twitter", "medium")):
        return CredibilityTier.TIER_4
    return CredibilityTier.TIER_3
