"""Rule-based headline classifier with rapidfuzz dedupe.

Classification is deterministic and explainable (keyword + source heuristics).
The Grok lens pass adds a richer interpretive layer on top, but classification
itself is reliable and never hallucinated.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from urllib.parse import urlparse

from rapidfuzz import fuzz

from app.models.headline import (
    CredibilityTier,
    Headline,
    HeadlineCluster,
    MacroChannel,
)

# ---------------------------------------------------------------------------
# Channel keyword map
# ---------------------------------------------------------------------------
CHANNEL_KEYWORDS: dict[str, list[str]] = {
    "monetary_policy": ["fomc", "fed", "rate cut", "rate hike", "qt", "qe", "dot plot"],
    "fiscal": ["deficit", "budget", "spending bill", "appropriations", "stimulus"],
    "treasury_issuance": ["refunding", "auction size", "coupon supply", "bill issuance", "treasury issuance"],
    "inflation": ["cpi", "pce", "ppi", "core inflation", "wage growth", "inflation"],
    "labor_growth": ["payroll", "unemployment", "ism", "pmi", "gdp", "jolts", "claims", "ip", "industrial production"],
    "central_bank_communication": ["lagarde", "powell", "bailey", "ueda", "kuroda", "speech", "press conference"],
    "credit_stress": ["spreads widen", "default", "downgrade", "credit", "loan loss", "cre"],
    "banking_liquidity": ["deposit", "h.8", "bank stress", "liquidity", "rrp", "tga", "btfp"],
    "geopolitical_risk": ["war", "missile", "strike", "attack", "houthi", "red sea", "ukraine", "taiwan"],
    "energy_commodities": ["opec", "crude", "oil", "natural gas", "lng", "gold", "copper", "wti", "brent"],
    "china": ["china", "pboc", "yuan", "cny", "shanghai", "evergrande"],
    "europe": ["ecb", "euro area", "eurozone", "bundesbank"],
    "japan": ["boj", "yen", "jpy", "tokyo"],
    "elections_regulation": ["election", "regulation", "antitrust", "doj", "ftc"],
    "tariffs_sanctions": ["tariff", "sanctions", "export control", "blacklist"],
    "market_plumbing_volatility": ["vix", "vol", "move index", "skew", "convexity", "gamma"],
    "positioning": ["positioning", "net length", "cot report", "hedge fund", "speculator"],
}

# ---------------------------------------------------------------------------
# Source -> tier
# ---------------------------------------------------------------------------
TIER_1 = {
    "federal reserve", "fed", "fomc", "u.s. treasury", "treasury", "european council",
    "ecb", "boe", "boj", "pboc", "bls", "bea", "eia", "imf", "world bank",
    "reuters", "ap", "associated press", "european commission",
}
TIER_2 = {"financial times", "ft", "wsj", "wall street journal", "bloomberg", "nikkei", "politico"}
TIER_3 = {"trade press", "sector", "cnbc", "marketwatch", "yahoo finance"}
TIER_4 = {"reddit", "twitter", "x", "substack", "telegram", "discord"}


def infer_tier(source: str) -> CredibilityTier:
    s = source.lower().strip()
    for k in TIER_1:
        if k in s:
            return CredibilityTier.TIER_1
    for k in TIER_2:
        if k in s:
            return CredibilityTier.TIER_2
    for k in TIER_3:
        if k in s:
            return CredibilityTier.TIER_3
    for k in TIER_4:
        if k in s:
            return CredibilityTier.TIER_4
    return CredibilityTier.TIER_3


_PRIORITY = (
    "geopolitical_risk", "tariffs_sanctions",
    "china", "europe", "japan",
    "monetary_policy", "treasury_issuance", "central_bank_communication",
    "credit_stress", "banking_liquidity",
    "inflation", "labor_growth",
    "energy_commodities", "fiscal", "elections_regulation",
    "market_plumbing_volatility", "positioning", "other",
)


def classify_channel(title: str, summary: str | None = None) -> MacroChannel:
    text = f"{title} {summary or ''}".lower()
    scores: dict[str, int] = defaultdict(int)
    for ch, kws in CHANNEL_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                scores[ch] += 1
    if not scores:
        return "other"
    max_score = max(scores.values())
    winners = [ch for ch, sc in scores.items() if sc == max_score]
    # break ties by static priority order
    for p in _PRIORITY:
        if p in winners:
            return p  # type: ignore[return-value]
    return winners[0]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------
def _canonical_url(url: str) -> str:
    try:
        p = urlparse(str(url))
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/").lower()
    except Exception:
        return str(url).lower()


def _norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKC", t).lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def dedupe(headlines: list[Headline], similarity_threshold: int = 88) -> list[Headline]:
    seen_urls: set[str] = set()
    kept: list[Headline] = []
    norm_titles: list[str] = []
    for h in headlines:
        u = _canonical_url(str(h.url))
        if u in seen_urls:
            continue
        nt = _norm_title(h.title)
        is_dup = any(fuzz.token_set_ratio(nt, prev) >= similarity_threshold for prev in norm_titles)
        if is_dup:
            continue
        seen_urls.add(u)
        norm_titles.append(nt)
        kept.append(h)
    return kept


# ---------------------------------------------------------------------------
# Cluster + score
# ---------------------------------------------------------------------------
def cluster_by_channel(headlines: list[Headline]) -> list[HeadlineCluster]:
    by_channel: dict[MacroChannel, list[Headline]] = defaultdict(list)
    for h in headlines:
        by_channel[h.category].append(h)

    clusters: list[HeadlineCluster] = []
    for ch, hs in by_channel.items():
        countries = sorted({h.country for h in hs if h.country})
        clusters.append(HeadlineCluster(
            name=_cluster_name(ch, hs),
            channel=ch,
            headlines=hs,
            countries=countries,
            summary="; ".join((h.summary or h.title) for h in hs[:3]),
        ))
    return clusters


def _cluster_name(channel: MacroChannel, hs: list[Headline]) -> str:
    if not hs:
        return channel
    return f"{channel} ({len(hs)} headlines)"


def score_clusters(clusters: list[HeadlineCluster]) -> list[HeadlineCluster]:
    """Heuristic scoring. Tier 4 / rumor headlines automatically attenuate.

    Real Grok lens-pass scoring is layered on top of this in causal_engine.
    """
    for c in clusters:
        n = len(c.headlines)
        rumor_n = sum(1 for h in c.headlines if h.is_rumor or h.is_unsourced)
        rumor_share = rumor_n / max(n, 1)
        # base scores keyed off channel
        market = 0.7 if c.channel in {"monetary_policy", "treasury_issuance", "inflation",
                                       "central_bank_communication", "energy_commodities",
                                       "market_plumbing_volatility"} else 0.5
        policy = 0.85 if c.channel in {"monetary_policy", "fiscal", "tariffs_sanctions",
                                        "central_bank_communication"} else 0.45
        surprise = min(0.2 + 0.15 * n, 0.95)
        cross_asset = 0.7 if c.channel in {"monetary_policy", "geopolitical_risk",
                                            "energy_commodities", "credit_stress"} else 0.5
        time_sens = 0.65 if c.channel in {"central_bank_communication", "market_plumbing_volatility"} else 0.5
        vol_pot = 0.75 if c.channel in {"market_plumbing_volatility", "geopolitical_risk"} else 0.4

        attenuation = 1.0 - 0.6 * rumor_share
        c.market_relevance = round(market * attenuation, 3)
        c.policy_relevance = round(policy * attenuation, 3)
        c.surprise_factor = round(surprise * attenuation, 3)
        c.cross_asset_impact = round(cross_asset * attenuation, 3)
        c.time_sensitivity = round(time_sens * attenuation, 3)
        c.vol_potential = round(vol_pot * attenuation, 3)
    return clusters
