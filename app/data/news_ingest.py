"""Headline ingestion.

Live mode pulls from GDELT (free), NewsAPI (if keyed), and an RSS bundle for
top-tier wires. Mock mode reads `fixtures/headlines_sample.json` so the test
suite + offline runs are deterministic.
"""

from __future__ import annotations

import json
import logging
import sys
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
    counts: dict[str, int] = {}
    out: list[Headline] = []
    if s.gdelt_enabled:
        gd = _fetch_gdelt(lookback_hours)
        counts["gdelt"] = len(gd)
        out.extend(gd)
    if s.newsapi_key:
        na = _fetch_newsapi(s.newsapi_key, lookback_hours)
        counts["newsapi"] = len(na)
        out.extend(na)
    rss = _fetch_rss(lookback_hours)
    counts["rss"] = len(rss)
    out.extend(rss)
    out = [h for h in out if h.published_at >= cutoff]
    before = len(out)
    out = [h for h in out if _passes_relevance(h)]
    print(f"news ingest: raw={counts} | post-relevance: {before}->{len(out)}", file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Macro relevance gate. Tier 1/2 sources bypass — central banks, Treasury,
# BLS/BEA/EIA, Reuters/AP wire, FT/WSJ/Bloomberg are macro by definition.
# Tier 3/4 must contain at least one term from the macro vocabulary to survive.
# ---------------------------------------------------------------------------
_MACRO_KEYWORDS = (
    # rates / monetary
    "fed", "fomc", "powell", "central bank", "interest rate", "rate cut", "rate hike",
    "monetary policy", "qt", "qe", "dot plot", "rate decision", "fed funds",
    # inflation
    "cpi", "ppi", "pce", "inflation", "disinflation", "deflation", "wage growth", "core inflation",
    # treasury / fiscal
    "treasury", "refunding", "auction", "coupon", "bill issuance", "deficit", "debt ceiling",
    "fiscal", "budget",
    # labor / growth
    "payroll", "unemployment", "jobless", "claims", "ism", "pmi", "gdp", "jolts", "nonfarm",
    "labor market", "jobs report",
    # cb / international
    "ecb", "lagarde", "boj", "ueda", "boe", "bailey", "pboc", "yuan", "yen", "euro area", "eurozone",
    # credit / banking
    "credit spread", "high yield", "junk bond", "bank stress", "bank deposit", "h.8", "rrp", "tga",
    "btfp", "regulator", "loan-to-deposit", "supervisory",
    # commodities / vol
    "opec", "crude", "wti", "brent", "natural gas", "lng", "gold", "silver", "copper",
    "vix", "move index", "implied vol", "convexity",
    # geopolitics with macro spillover
    "tariff", "sanctions", "export control", "houthi", "red sea", "ukraine", "taiwan", "russia oil",
    # markets / positioning
    "yield", "curve", "dxy", "dollar index", "futures", "hedge fund", "positioning",
    "options flow", "term premium", "real yield", "bond market", "stock market",
)


def _passes_relevance(h: Headline) -> bool:
    if h.tier in (CredibilityTier.TIER_1, CredibilityTier.TIER_2):
        return True
    text = f"{h.title} {h.summary or ''}".lower()
    return any(kw in text for kw in _MACRO_KEYWORDS)


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
    # Theme-based filter is far more precise than free-text. Combined with a
    # domain allow-list of macro-grade sources, this kills the local-newspaper
    # noise that the previous query was pulling in.
    domains = (
        "domain:reuters.com OR domain:apnews.com OR domain:ft.com OR domain:wsj.com "
        "OR domain:bloomberg.com OR domain:cnbc.com OR domain:marketwatch.com "
        "OR domain:economist.com OR domain:nikkei.com OR domain:politico.com"
    )
    themes = (
        "theme:ECON_INTEREST_RATES OR theme:ECON_INFLATION OR theme:ECON_CENTRAL_BANK "
        "OR theme:ECON_DEBT OR theme:ECON_TRADE_DEAL OR theme:ECON_BANK_DEBT "
        "OR theme:ECON_BANKRUPTCY OR theme:ECON_STIMULUS OR theme:ECON_MONOPOLY"
    )
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": f"({domains}) AND ({themes}) sourcelang:eng",
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 50,
        "timespan": f"{lookback_hours}h",
        "sort": "datedesc",
    }
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.get(url, params=params)
            if r.status_code == 429:
                log.warning("GDELT rate-limited (429); skipping this run")
                return []
            r.raise_for_status()
            if not r.text or not r.text.strip().startswith("{"):
                log.warning("GDELT returned non-JSON body (likely throttle page); skipping")
                return []
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
    # Phrase-quoted OR + domain allow-list. NewsAPI tokenises unquoted text, so
    # `Federal Reserve` was matching anything with "federal" or "reserve" — junk.
    q = (
        '"Federal Reserve" OR "FOMC" OR "ECB" OR "Bank of Japan" OR '
        '"core PCE" OR "CPI" OR "Treasury refunding" OR "OPEC" OR '
        '"yield curve" OR "10-year yield" OR "rate cut" OR "rate hike"'
    )
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": q,
        "from": cutoff,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 50,
        "domains": "reuters.com,apnews.com,ft.com,wsj.com,bloomberg.com,cnbc.com,marketwatch.com,economist.com,nikkei.com",
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
