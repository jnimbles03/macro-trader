"""Persona-weighting: regime → persona relevance scoring.

We do NOT impersonate the named investors. We use the *analytical lens*
associated with each — rates/duration, reflexivity, debt cycles, etc. — and
blend the top 3-5 most regime-relevant lenses into one synthesis.
"""

from __future__ import annotations

from app.models.macro_signal import Regime

PERSONAS: dict[str, str] = {
    "Gross": "rates, duration, carry, convexity, credit cycles, Fed reaction function",
    "Gundlach": "bond-market signaling, curve structure, credit stress, mortgage/credit",
    "Druckenmiller": "liquidity regimes, asymmetric macro, central bank inflection",
    "Soros": "reflexivity, feedback loops, policy mistakes, currency/rates dislocations",
    "PTJ": "crisis convexity, trend inflections, macro risk/reward",
    "Dalio": "debt cycles, policy mix, currency regimes, balance sheet mechanics",
    "Ackman": "concentrated catalyst-driven, public policy catalysts, risk-defined",
    "Chanos": "structural shorts, fraud/bubble detection, unsustainable narratives",
    "Burry": "crowded risk, mispriced tails, hidden leverage, convex downside",
    "Tepper": "policy-put / liquidity awareness, crisis entry points",
    "Bacon": "rates, FX, commodities, vol across global regimes",
    "Howard": "rates/FX/commodities macro vol",
}

# regime -> weight overrides (additive on a 0.3 baseline; clamped to [0, 1])
REGIME_WEIGHTS: dict[Regime, dict[str, float]] = {
    Regime.LIQUIDITY_EXPANSION: {"Druckenmiller": 0.55, "Tepper": 0.5, "Dalio": 0.4, "PTJ": 0.3},
    Regime.LIQUIDITY_WITHDRAWAL: {"Gross": 0.6, "Gundlach": 0.6, "Druckenmiller": 0.55, "Dalio": 0.45, "Bacon": 0.35},
    Regime.INFLATION_SCARE: {"Gross": 0.55, "Druckenmiller": 0.5, "Dalio": 0.5, "Bacon": 0.4, "PTJ": 0.35},
    Regime.GROWTH_SCARE: {"Gundlach": 0.55, "PTJ": 0.5, "Tepper": 0.45, "Burry": 0.3},
    Regime.POLICY_MISTAKE: {"Soros": 0.65, "Druckenmiller": 0.6, "Bacon": 0.5, "PTJ": 0.45},
    Regime.CREDIT_STRESS: {"Gundlach": 0.6, "Burry": 0.6, "Chanos": 0.55, "Tepper": 0.5},
    Regime.GEOPOLITICAL_SHOCK: {"PTJ": 0.6, "Soros": 0.5, "Bacon": 0.5, "Howard": 0.45},
    Regime.RISK_ON_MELTUP: {"Druckenmiller": 0.5, "Tepper": 0.45, "Burry": 0.4, "Chanos": 0.4},
    Regime.RISK_OFF_DELEVERAGING: {"PTJ": 0.6, "Gundlach": 0.5, "Dalio": 0.45, "Burry": 0.45},
    Regime.NO_SIGNAL: {},
    Regime.CONFLICTED: {"Soros": 0.4, "PTJ": 0.4, "Gundlach": 0.4},
}


def weight_personas(regime: Regime) -> dict[str, float]:
    base = 0.3
    out = {name: base for name in PERSONAS}
    for name, w in REGIME_WEIGHTS.get(regime, {}).items():
        out[name] = max(out[name], w)
    return out


def top_personas(regime: Regime, n: int = 4) -> list[tuple[str, float, str]]:
    weights = weight_personas(regime)
    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return [(name, round(w, 2), PERSONAS[name]) for name, w in ranked]


def convergence_dissent(regime: Regime) -> tuple[list[str], list[str]]:
    """Names of personas pointing the same way ( ≥3 ) and notable disagreers."""
    top = [n for n, _, _ in top_personas(regime, n=4)]
    convergence = top if len(top) >= 3 else []
    pairs = [("Chanos", "Ackman"), ("Burry", "Druckenmiller")]
    dissent = [a for a, b in pairs if a in PERSONAS and b in PERSONAS]
    return convergence, dissent
