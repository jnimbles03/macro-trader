"""Causal engine.

Primary LLM (Grok) does the synthesis. Opus validates afterward in
trade_selector.

The engine is also responsible for generating *deterministic* output in
MOCK_DATA mode so that the test suite can run offline.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.config import get_settings
from app.data.llm_client import GrokClient, parse_json_or_empty
from app.models.headline import HeadlineCluster
from app.models.macro_signal import RegimeAssessment

log = logging.getLogger(__name__)

CAUSAL_SYSTEM = """\
You are the analytical core of Macro Options Scout, a trading research agent.

You think like a sharp macro PM: concise, skeptical, causal. No hype, no fake
certainty. Always focused on asymmetry, catalyst, liquidity, and what breaks
the thesis.

You do NOT impersonate famous investors. You synthesize across analytical
lenses (rates/duration/Druckenmiller-style liquidity inflection/etc) using the
persona weights provided.

You will receive:
  - the dominant macro regime + confidence
  - the top persona weights for this run (only the top 3-5 should drive the call)
  - top headline clusters with credibility tiers
  - macro signal snapshot (yields, curve, DXY, VIX/MOVE)

You return JSON ONLY (no prose) with this shape:

{
  "executive_read": ["bullet1", "bullet2", ...],     // 3-5 bullets
  "regime_explanation": "plain English explanation",
  "convergence": ["Persona", ...],                   // ≥3 means strong convergence
  "dissent": ["Persona", ...],
  "candidate_trades": [
    {
       "slot": "spread" | "yolo",
       "name": "...",
       "root": "ZN" | "ES" | ...,
       "direction": "bullish" | "bearish" | "neutral" | "long_vol" | "short_vol",
       "structure": "bear_put_spread" | "single_long" | ...,
       "expiration": "YYYY-MM-DD",
       "legs": [
          {"action": "BUY"|"SELL", "option_type": "C"|"P", "strike": 110.0, "premium": 0.49}
       ],
       "catalyst": "...",
       "causal_chain": "headline -> policy -> asset -> option expression",
       "why_this_structure": "...",
       "what_kills_thesis": "...",
       "why_probably_dumb": "..."          // REQUIRED for yolo, null otherwise
    }
  ]
}

Rules:
- Never fabricate prices/Greeks/strikes — only reference values present in the
  provided chain snapshot.
- If the regime is "no_signal", return an empty candidate_trades array.
- If the regime is "conflicted" but >=3 personas in the convergence list agree
  on a thesis direction (and total cluster weight isn't tiny), you MAY still
  propose ONE trade — pick the cleanest expression (spread OR yolo, not both)
  and explain in why_probably_dumb why this is lower conviction than usual.
- Otherwise (weak total weight, no convergence, no clean expression), return
  empty rather than manufacturing a thesis.
- Defined-risk spread MUST have max_gain/max_loss >= 2.0 at expiration.
- YOLO MUST be a single long option (no naked shorts; no debit spreads).
- Naked short options are never permitted in either slot.
"""


@dataclass
class CausalOutput:
    raw_json: dict
    executive_read: list[str]
    regime_explanation: str
    convergence: list[str]
    dissent: list[str]
    candidate_trades: list[dict]
    model_used: str


def run_causal_engine(regime: RegimeAssessment,
                      clusters: list[HeadlineCluster],
                      chain_snapshots: list[dict],
                      market_tape: dict) -> CausalOutput:
    """Run Grok over the synthesized payload."""
    s = get_settings()

    if s.mock_data:
        return _mock_causal_output(regime, clusters)

    client = GrokClient(s)
    payload = {
        "regime": regime.regime.value,
        "regime_confidence": regime.confidence,
        "regime_explanation": regime.explanation,
        "persona_weights": regime.persona_weights,
        "persona_convergence": regime.convergence,
        "persona_dissent": regime.dissent,
        "clusters": [
            {
                "name": c.name,
                "channel": c.channel,
                "best_tier": c.best_tier.value,
                "composite_score": c.composite_score,
                "summary": c.summary,
                "headlines": [
                    {"title": h.title, "source": h.source, "tier": h.tier.value,
                     "url": str(h.url), "is_rumor": h.is_rumor}
                    for h in c.headlines
                ],
            } for c in clusters
        ],
        "chains": chain_snapshots,
        "market_tape": market_tape,
    }
    user = "INPUT:\n" + json.dumps(payload, default=str)
    resp = client.chat(CAUSAL_SYSTEM, user, response_format_json=True, max_tokens=4000)
    parsed = parse_json_or_empty(resp.text)
    return CausalOutput(
        raw_json=parsed,
        executive_read=parsed.get("executive_read", []),
        regime_explanation=parsed.get("regime_explanation", regime.explanation),
        convergence=parsed.get("convergence", []),
        dissent=parsed.get("dissent", []),
        candidate_trades=parsed.get("candidate_trades", []),
        model_used=resp.model,
    )


# ---------------------------------------------------------------------------
# Mock-mode output — deterministic, sourced from fixture chains
# ---------------------------------------------------------------------------
def _mock_causal_output(regime: RegimeAssessment, clusters: list[HeadlineCluster]) -> CausalOutput:
    # Build a defined-risk bear-put spread on ZN and a YOLO single long ES put.
    # Strikes/premiums match fixtures in tests.
    spread_trade = {
        "slot": "spread",
        "name": "ZN bear put spread — Treasury refunding + sticky core PCE",
        "root": "ZN",
        "direction": "bearish",
        "structure": "bear_put_spread",
        "expiration": "2026-05-23",
        "legs": [
            {"action": "BUY",  "option_type": "P", "strike": 110.0,  "premium": 0.49},
            {"action": "SELL", "option_type": "P", "strike": 108.5, "premium": 0.12},
        ],
        "catalyst": "Q3 refunding lifts coupon supply; April core PCE 0.4% m/m vs 0.3% expected",
        "causal_chain": (
            "Refunding announcement + sticky core PCE -> term premium repricing higher "
            "-> 10y yields drift up -> ZN drifts lower -> bear-put captures defined-risk "
            "downside without needing a violent move."
        ),
        "why_this_structure": (
            "Defined risk; the move is a drift not a shock. Spread caps premium decay vs "
            "outright long puts and clears the 2:1 floor at expiration."
        ),
        "what_kills_thesis": (
            "Soft Friday NFP, dovish Fedspeak, or a credit-stress flight-to-quality bid; "
            "all would re-bid duration."
        ),
        "why_probably_dumb": None,
    }
    yolo_trade = {
        "slot": "yolo",
        "name": "ES long put — China PMI miss + ISM stagflation tinge + crowded longs",
        "root": "ES",
        "direction": "bearish",
        "structure": "single_long",
        "expiration": "2026-05-30",
        "legs": [
            {"action": "BUY", "option_type": "P", "strike": 4900.0, "premium": 6.55},
        ],
        "catalyst": "China PMI 49.4 + ISM 47.8 with prices paid 60.1 + hedge-fund net long extreme",
        "causal_chain": (
            "Demand softening + sticky input prices + crowded long positioning -> any "
            "vol-control or systematic de-grossing forces correlated equity selling -> "
            "5%+ drawdown captures convex put payoff."
        ),
        "why_this_structure": (
            "Single long put = uncapped convex payoff with premium-only risk. Spreads cap "
            "the very tail this trade is hunting."
        ),
        "what_kills_thesis": (
            "Continued policy-put behavior, soft inflation print pivoting Fed dovish, or "
            "China stimulus headline in window."
        ),
        "why_probably_dumb": (
            "Buying tail puts ahead of an unconfirmed correction is statistically a "
            "premium-burn trade; positioning extremes can stay extreme; catalyst path "
            "requires a specific systematic-flow story to play out within ~28 days."
        ),
    }
    return CausalOutput(
        raw_json={"mock": True},
        executive_read=[
            "QT continues; Q3 refunding lifts coupon supply; sticky core PCE drives term-premium repricing.",
            "ECB tilt hawkish on services inflation; BoE Bailey nudges dovish — DXY caught between flows.",
            "China PMI back in contraction; deflation pulse persists.",
            "Crowded equity long positioning + ISM stagflation tinge raises asymmetric drawdown risk.",
        ],
        regime_explanation=regime.explanation,
        convergence=["Gross", "Gundlach", "Druckenmiller"],
        dissent=["Tepper", "Ackman"],
        candidate_trades=[spread_trade, yolo_trade],
        model_used="grok-mock",
    )
