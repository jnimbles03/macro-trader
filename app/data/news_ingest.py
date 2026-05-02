"""Headline query layer.

By default, reads from the data warehouse (`headlines` table). Use `live=True`
to bypass the warehouse and call vendor APIs directly — useful for `--live`
pokes when you want bleeding-edge data and the cron hasn't run yet.

Mock mode (`MOCK_DATA=true`) reads `fixtures/headlines_sample.json` so the
test suite + offline runs are deterministic.

The actual fetch logic for each vendor lives in `app/ingest/{vendor}.py` —
this module only chooses where to read from.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.data.cache import cache_key, cached_call
from app.models.headline import CredibilityTier, Headline
from app.storage.repository import query_headlines

log = logging.getLogger(__name__)


def fetch_recent_headlines(*, lookback_hours: int = 24, fresh: bool = False,
                           live: bool = False) -> list[Headline]:
    s = get_settings()
    key = cache_key("headlines", lookback_hours, "live" if live else "warehouse",
                    "mock" if s.mock_data else "real")
    return cached_call(
        key,
        ttl_seconds=s.cache_headlines_min * 60,
        fresh=fresh,
        loader=lambda: _load(s, lookback_hours, live=live),
    )


def _load(s, lookback_hours: int, *, live: bool) -> list[Headline]:
    if s.mock_data:
        return _load_fixture()

    if live:
        return _load_live(lookback_hours)

    # Default path: read from warehouse.
    since = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    rows = query_headlines(since=since, limit=500)
    out = [h for h in rows if _passes_relevance(h)]
    print(f"news query (warehouse): {len(rows)} rows -> {len(out)} after relevance filter",
          file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Live bypass — fetch from vendors directly. Useful when you don't want to
# wait for the next cron tick. Persists what it fetches into the warehouse
# as a side effect so the data is preserved.
# ---------------------------------------------------------------------------
def _load_live(lookback_hours: int) -> list[Headline]:
    from app.ingest import gdelt, newsapi, rss
    from app.ingest.runner import run_one

    counts = {}
    for name, fn in (("gdelt", gdelt.ingest), ("newsapi", newsapi.ingest), ("rss", rss.ingest)):
        res = run_one(name, fn, lookback_hours=lookback_hours)
        counts[name] = res.rows_added
    print(f"news ingest (live): {counts}", file=sys.stderr)

    since = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    rows = query_headlines(since=since, limit=500)
    return [h for h in rows if _passes_relevance(h)]


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
