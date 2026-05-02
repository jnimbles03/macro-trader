"""Regime detector — uses macro signals + cluster mix to label the regime.

Output is one of the Regime enum values. "no_signal" is a valid output and
triggers NO TRADE on both slots.
"""

from __future__ import annotations

from app.models.headline import HeadlineCluster
from app.models.macro_signal import MacroSignal, Regime, RegimeAssessment


def _signal(signals: list[MacroSignal], series_id: str) -> MacroSignal | None:
    for s in signals:
        if s.series_id == series_id:
            return s
    return None


def detect_regime(clusters: list[HeadlineCluster], signals: list[MacroSignal]) -> RegimeAssessment:
    # Total headline weight (excluding rumor-only clusters)
    total_score = sum(c.composite_score for c in clusters)
    if total_score < 0.6 or len(clusters) <= 1:
        return RegimeAssessment(
            regime=Regime.NO_SIGNAL,
            confidence=0.7,
            explanation="Total cluster weight low; nothing actionable in last 24h.",
            signals=signals,
        )

    # signal aggregates
    inflation_w = sum(c.composite_score for c in clusters if c.channel in {"inflation"})
    growth_w = sum(c.composite_score for c in clusters if c.channel in {"labor_growth", "china"})
    policy_w = sum(c.composite_score for c in clusters if c.channel in {"monetary_policy", "central_bank_communication", "treasury_issuance"})
    geo_w = sum(c.composite_score for c in clusters if c.channel in {"geopolitical_risk", "tariffs_sanctions"})
    credit_w = sum(c.composite_score for c in clusters if c.channel in {"credit_stress", "banking_liquidity"})
    vol_w = sum(c.composite_score for c in clusters if c.channel in {"market_plumbing_volatility"})

    move = _signal(signals, "MOVE")
    vix = _signal(signals, "VIXCLS")
    t10y2y = _signal(signals, "T10Y2Y")
    dff = _signal(signals, "DFF")

    # heuristic priority
    if geo_w > 0.6 and (move and move.value > 110):
        regime = Regime.GEOPOLITICAL_SHOCK
        explanation = "Geopolitical cluster dominant + elevated rates vol (MOVE)."
    elif credit_w > 0.5:
        regime = Regime.CREDIT_STRESS
        explanation = "Credit/banking liquidity cluster elevated."
    elif inflation_w > 0.5 and policy_w > 0.5:
        regime = Regime.INFLATION_SCARE
        explanation = "Inflation surprise + central bank rhetoric on services inflation."
    elif growth_w > 0.6 and inflation_w < 0.3:
        regime = Regime.GROWTH_SCARE
        explanation = "Growth weakness without offsetting inflation reassurance."
    elif policy_w > 0.6 and t10y2y and t10y2y.value < 0:
        regime = Regime.LIQUIDITY_WITHDRAWAL
        explanation = "Policy-driven; inverted curve; QT/issuance backdrop."
    elif vol_w > 0.4 and vix and vix.value < 18:
        regime = Regime.RISK_ON_MELTUP
        explanation = "Vol-suppressed equities with positioning long."
    else:
        regime = Regime.CONFLICTED
        explanation = "Multiple cross-cutting drivers; no clean regime."

    confidence = round(min(0.95, 0.4 + 0.5 * (total_score / max(1, len(clusters)))), 2)
    return RegimeAssessment(regime=regime, confidence=confidence, explanation=explanation, signals=signals)
