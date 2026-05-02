"""Regime detector — uses macro signals + cluster mix to label the regime.

Output is one of the Regime enum values. "no_signal" is a valid output and
triggers NO TRADE on both slots.

Design notes:
- Cluster scores are heavily attenuated by credibility tier. A typical
  tier_3-heavy live run produces bucket weights in the 0.30-0.50 range
  even when the underlying themes are clear. Hard thresholds at 0.5/0.6
  used to push almost every live run into CONFLICTED. Switched to a
  share-of-total approach: pick the dominant bucket if it has >=30% of
  total weight, only fall back to CONFLICTED when no bucket dominates.
- Energy commodity stories count as inflation pressure (oil shock = sticky
  CPI input).
"""

from __future__ import annotations

from app.models.headline import HeadlineCluster
from app.models.macro_signal import MacroSignal, Regime, RegimeAssessment


def _signal(signals: list[MacroSignal], series_id: str) -> MacroSignal | None:
    for s in signals:
        if s.series_id == series_id:
            return s
    return None


# Channel -> macro bucket. A channel can only belong to one bucket.
_BUCKETS: dict[str, str] = {
    "inflation": "inflation",
    "energy_commodities": "inflation",      # oil/gas shocks are inflation pressure
    "labor_growth": "growth",
    "china": "growth",
    "monetary_policy": "policy",
    "central_bank_communication": "policy",
    "treasury_issuance": "policy",
    "geopolitical_risk": "geo",
    "tariffs_sanctions": "geo",
    "credit_stress": "credit",
    "banking_liquidity": "credit",
    "market_plumbing_volatility": "vol",
    "positioning": "vol",
}


def detect_regime(clusters: list[HeadlineCluster], signals: list[MacroSignal]) -> RegimeAssessment:
    total_score = sum(c.composite_score for c in clusters)

    # NO_SIGNAL gate. Tighter than before: just total weight, no min cluster count.
    # (A single rich tier_1 cluster can be a real signal — we don't punish that.)
    if total_score < 0.4:
        return RegimeAssessment(
            regime=Regime.NO_SIGNAL,
            confidence=0.7,
            explanation="Total cluster weight low; nothing actionable in last 24h.",
            signals=signals,
        )

    # Aggregate weight per macro bucket.
    weights: dict[str, float] = {
        "inflation": 0.0, "growth": 0.0, "policy": 0.0,
        "geo": 0.0, "credit": 0.0, "vol": 0.0, "other": 0.0,
    }
    for c in clusters:
        bucket = _BUCKETS.get(c.channel, "other")
        weights[bucket] += c.composite_score

    macro_total = sum(v for k, v in weights.items() if k != "other")
    if macro_total <= 0:
        # Lots of headlines but none macro-relevant.
        return RegimeAssessment(
            regime=Regime.NO_SIGNAL, confidence=0.6,
            explanation="Coverage is broad but lacks macro-actionable channels.",
            signals=signals,
        )

    move = _signal(signals, "MOVE")
    vix = _signal(signals, "VIXCLS")
    t10y2y = _signal(signals, "T10Y2Y")
    dff = _signal(signals, "DFF")

    # Dominant bucket: the one with the highest weight, IF it's at least 30% of
    # the macro total. Below 30% means no real winner -> CONFLICTED.
    dominant = max((k for k in weights if k != "other"), key=lambda k: weights[k])
    dominant_share = weights[dominant] / macro_total

    if dominant_share < 0.30:
        regime = Regime.CONFLICTED
        explanation = "No bucket dominant; cross-cutting drivers."
    elif dominant == "geo" and weights["geo"] > 0.4 and (move is None or move.value > 100):
        regime = Regime.GEOPOLITICAL_SHOCK
        explanation = "Geopolitical cluster dominant + elevated rates vol (MOVE)."
    elif dominant == "credit":
        regime = Regime.CREDIT_STRESS
        explanation = "Credit/banking liquidity cluster elevated."
    elif dominant == "inflation" or (weights["inflation"] >= 0.30 and weights["policy"] >= 0.30):
        # Inflation alone OR inflation + hawkish-policy combo = inflation scare
        regime = Regime.INFLATION_SCARE
        explanation = "Inflation/energy cluster dominant; hawkish policy backdrop." \
            if weights["policy"] >= 0.30 else "Inflation/energy pressures dominant."
    elif dominant == "growth" and weights["inflation"] < 0.30:
        regime = Regime.GROWTH_SCARE
        explanation = "Growth weakness without offsetting inflation reassurance."
    elif dominant == "policy":
        if t10y2y and t10y2y.value < 0:
            regime = Regime.LIQUIDITY_WITHDRAWAL
            explanation = "Policy-driven; inverted curve; QT/issuance backdrop."
        else:
            regime = Regime.POLICY_MISTAKE
            explanation = "Policy cluster dominant; positive-slope curve suggests anchoring risk."
    elif dominant == "vol" and vix and vix.value < 18:
        regime = Regime.RISK_ON_MELTUP
        explanation = "Vol-suppressed equities with positioning long."
    else:
        regime = Regime.CONFLICTED
        explanation = f"Dominant={dominant} but criteria not met for clean classification."

    # Confidence: blend of (a) overall macro weight and (b) how dominant the
    # winning bucket is. High weight + clear winner = high confidence.
    weight_factor = min(1.0, macro_total / 2.0)            # saturates at total=2.0
    dominance_factor = min(1.0, dominant_share / 0.6)       # saturates at 60% share
    raw_conf = 0.40 + 0.30 * weight_factor + 0.25 * dominance_factor
    confidence = round(min(0.95, raw_conf), 2)
    if regime == Regime.NO_SIGNAL:
        confidence = 0.7
    if regime == Regime.CONFLICTED:
        confidence = round(min(confidence, 0.65), 2)

    return RegimeAssessment(
        regime=regime, confidence=confidence,
        explanation=explanation, signals=signals,
    )
