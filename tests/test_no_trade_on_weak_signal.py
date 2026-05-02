"""Most important test — single low-quality headline should NOT manufacture trades.

The pipeline must surface NO TRADE on both slots, not invent a thesis.
"""

from datetime import datetime, timezone

from app.analysis.headline_classifier import cluster_by_channel, score_clusters
from app.analysis.regime_detector import detect_regime
from app.analysis.trade_selector import select_trades
from app.models.headline import CredibilityTier, Headline
from app.models.trade_idea import NoTradeReason


def test_single_tier4_headline_yields_no_trade_on_both_slots():
    headlines = [Headline(
        title="anon: Fed will cut 50bp in June, mark my words",
        source="X",
        tier=CredibilityTier.TIER_4,
        published_at=datetime.now(tz=timezone.utc),
        url="https://x.com/anon/1",
        category="monetary_policy",
        is_rumor=True,
        is_unsourced=True,
    )]
    clusters = score_clusters(cluster_by_channel(headlines))
    regime = detect_regime(clusters, signals=[])
    # Should be no_signal (low total score) — engine must short-circuit.
    sel = select_trades(
        regime=regime,
        clusters=clusters,
        chains_by_root={},
        candidate_trades=[],
        model_primary="grok-mock",
        executive_read=[],
        convergence=[],
        dissent=[],
    )
    assert sel.spread.trade is None
    assert sel.yolo.trade is None
    assert sel.spread.no_trade_reason in {NoTradeReason.REGIME_NO_SIGNAL, NoTradeReason.WEAK_SIGNAL}
    assert sel.yolo.no_trade_reason in {NoTradeReason.REGIME_NO_SIGNAL, NoTradeReason.WEAK_SIGNAL}
