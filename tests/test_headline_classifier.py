"""Classification + dedupe sanity."""

from datetime import datetime, timezone

from app.analysis.headline_classifier import (
    classify_channel,
    cluster_by_channel,
    dedupe,
    infer_tier,
    score_clusters,
)
from app.models.headline import CredibilityTier, Headline


def _h(title, source, tier, cat="other"):
    return Headline(
        title=title, source=source, tier=tier,
        published_at=datetime.now(tz=timezone.utc),
        url=f"https://example.com/{abs(hash(title))}",
        category=cat,
    )


def test_classify_channel_basic():
    assert classify_channel("FOMC minutes signal pause") == "monetary_policy"
    assert classify_channel("April core PCE prints hot") == "inflation"
    assert classify_channel("OPEC+ extends voluntary cuts") == "energy_commodities"
    assert classify_channel("China PMI back below 50") == "china"
    assert classify_channel("Random unrelated text") == "other"


def test_infer_tier_routes_to_t1_t2_t4():
    assert infer_tier("Federal Reserve") == CredibilityTier.TIER_1
    assert infer_tier("Reuters") == CredibilityTier.TIER_1
    assert infer_tier("Bloomberg") == CredibilityTier.TIER_2
    assert infer_tier("Reddit") == CredibilityTier.TIER_4


def test_dedupe_url_and_similarity():
    a = _h("Fed minutes signal pause is on table", "Reuters", CredibilityTier.TIER_1)
    b = _h("Fed minutes signal a pause is on the table", "AP", CredibilityTier.TIER_1)
    c = _h("OPEC+ extends voluntary cuts", "FT", CredibilityTier.TIER_2)
    out = dedupe([a, b, c])
    titles = [h.title for h in out]
    assert any("OPEC" in t for t in titles)
    # a/b are near-duplicates — only one should survive
    fed_count = sum(1 for t in titles if "Fed minutes" in t)
    assert fed_count == 1


def test_cluster_and_score_attenuates_rumors():
    rumor = Headline(
        title="anon: Fed will cut 50bp", source="X", tier=CredibilityTier.TIER_4,
        published_at=datetime.now(tz=timezone.utc), url="https://x.com/anon/1",
        category="monetary_policy", is_rumor=True, is_unsourced=True,
    )
    real = _h("FOMC minutes show open debate over QT pace", "Federal Reserve",
              CredibilityTier.TIER_1, cat="monetary_policy")
    clusters = score_clusters(cluster_by_channel([rumor, real]))
    assert len(clusters) == 1
    c = clusters[0]
    # Mixed cluster — composite should be > 0 but rumor should attenuate
    only_real = score_clusters(cluster_by_channel([real]))[0]
    assert c.composite_score < only_real.composite_score
