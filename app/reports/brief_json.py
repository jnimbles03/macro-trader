"""JSON serialization of a TradeBrief for the React UI.

Produces a flat, UI-shaped dict — no pydantic models leaked, no nested
dataclasses. Anything the SPA needs to render lives here.
"""

from __future__ import annotations

from typing import Any

from app.models.trade_idea import TradeIdea
from app.reports.trade_report import TradeBrief


def _trade_to_dict(trade: TradeIdea | None) -> dict[str, Any] | None:
    if trade is None:
        return None
    rr = trade.rr_ratio if trade.rr_ratio < 1e6 else None
    legs = [
        {
            "action": l.action,
            "quantity": l.quantity,
            "option_type": l.option_type.value,
            "strike": l.strike,
            "expiration": l.expiration.isoformat(),
            "premium": l.premium,
            "iv": l.iv,
            "delta": l.delta,
            "gamma": l.gamma,
            "theta": l.theta,
            "vega": l.vega,
        }
        for l in trade.legs
    ]
    verdict = None
    if trade.validator_verdict is not None:
        v = trade.validator_verdict
        verdict = {
            "decision": v.decision,
            "news_check": v.news_check,
            "trade_theory_check": v.trade_theory_check,
            "risk_reward_check": v.risk_reward_check,
            "option_strategy_check": v.option_strategy_check,
            "issues": v.issues,
            "revisions_suggested": v.revisions_suggested,
            "confidence": v.confidence,
        }
    return {
        "kind": trade.kind.value,
        "name": trade.name,
        "root": trade.root,
        "underlying_symbol": trade.underlying_symbol,
        "direction": trade.direction,
        "structure": trade.structure.value,
        "expiration": trade.expiration.isoformat(),
        "legs": legs,
        "entry_debit_credit": trade.entry_debit_credit,
        "max_loss": trade.max_loss,
        "max_profit": trade.max_profit if trade.max_profit < 1e9 else None,
        "rr_ratio": rr,
        "breakeven": trade.breakeven,
        "expected_move_pct": trade.expected_move_pct,
        "probability_itm": trade.probability_itm,
        "bid_ask_pct_worst": trade.bid_ask_pct_worst,
        "min_volume": trade.min_volume,
        "min_open_interest": trade.min_open_interest,
        "catalyst": trade.catalyst,
        "causal_chain": trade.causal_chain,
        "why_this_structure": trade.why_this_structure,
        "what_kills_thesis": trade.what_kills_thesis,
        "why_probably_dumb": trade.why_probably_dumb,
        "invalidation": trade.invalidation,
        "stop_logic": trade.stop_logic,
        "profit_taking_logic": trade.profit_taking_logic,
        "suggested_contracts": trade.suggested_contracts,
        "risk_dollars": trade.risk_dollars,
        "sizing_note": trade.sizing_note,
        "validator_verdict": verdict,
    }


def _slot_to_dict(slot) -> dict[str, Any]:
    return {
        "trade": _trade_to_dict(slot.trade),
        "no_trade_reason": slot.no_trade_reason.value if slot.no_trade_reason else None,
        "detail": slot.detail,
    }


# Channel -> single most-impacted ETF in the markets-panel set.
# Picks the cleanest ETF expression of each macro channel so the hero
# bullet can show "Lagarde hawkish — TLT -1.2% (2d)" at a glance.
_CHANNEL_ETF: dict[str, str] = {
    "monetary_policy": "TLT",
    "central_bank_communication": "TLT",
    "treasury_issuance": "TLT",
    "inflation": "TLT",
    "labor_growth": "SPY",
    "credit_stress": "HYG",
    "banking_liquidity": "HYG",
    "geopolitical_risk": "VIXY",
    "energy_commodities": "EEM",       # no oil ETF in the panel; EM is the
                                        # next-best single-ETF proxy for an
                                        # OPEC / oil-supply catalyst
    "china": "FXI",
    "europe": "EWG",
    "japan": "EEM",
    "elections_regulation": "SPY",
    "tariffs_sanctions": "FXI",
    "market_plumbing_volatility": "VIXY",
    "positioning": "SPY",
    "fiscal": "TLT",
    "other": "SPY",
}


def _impact_tier(score: float) -> str:
    """Bucket cluster composite score into a t-shirt size.

    `composite_score` is a 0..~0.7 weighted aggregate (relevance, surprise,
    cross-asset impact, time sensitivity, vol potential, attenuated by
    source credibility). Thresholds picked so the top of a typical brief
    has 1-2 XL items, 2-3 L items, the rest M/S.
    """
    if score >= 0.55:
        return "XL"
    if score >= 0.40:
        return "L"
    if score >= 0.25:
        return "M"
    return "S"


def _insight_line(cluster) -> str:
    """One-line distillation of a cluster for the hero list.

    Prefer the cluster summary (already authored by the headline classifier);
    fall back to the highest-tier headline's title.
    """
    if cluster.summary:
        first = cluster.summary.split(";")[0].strip().rstrip(".")
        if first:
            return first
    if cluster.headlines:
        return cluster.headlines[0].title
    return cluster.name


def brief_to_dict(brief: TradeBrief) -> dict[str, Any]:
    sel = brief.selector
    ranked_clusters = sorted(brief.clusters, key=lambda c: c.composite_score, reverse=True)[:5]
    clusters = [
        {
            "name": c.name,
            "channel": c.channel,
            "best_tier": c.best_tier.value,
            "composite_score": c.composite_score,
            "impact": _impact_tier(c.composite_score),
            "summary": c.summary,
            "headlines": [
                {
                    "title": h.title,
                    "source": h.source,
                    "tier": h.tier.value,
                    "url": str(h.url),
                    "published_at": h.published_at.isoformat(),
                }
                for h in c.headlines[:8]
            ],
        }
        for c in ranked_clusters
    ]
    insights = [
        {
            "impact": _impact_tier(c.composite_score),
            "score": round(c.composite_score, 4),
            "text": _insight_line(c),
            "channel": c.channel,
            "cluster_name": c.name,
            "etf_label": _CHANNEL_ETF.get(c.channel),
        }
        for c in ranked_clusters
    ]
    signals = [
        {
            "series_id": s.series_id,
            "label": s.label,
            "value": s.value,
            "units": s.units,
            "as_of": s.as_of.isoformat(),
            "surprise_vs_consensus": s.surprise_vs_consensus,
        }
        for s in brief.signals
    ]
    return {
        "generated_at": brief.generated_at.isoformat(),
        "regime": {
            "regime": brief.regime.regime.value,
            "confidence": brief.regime.confidence,
            "explanation": brief.regime.explanation,
        },
        "personas": [
            {"name": name, "weight": weight, "lens": lens}
            for name, weight, lens in brief.persona_top
        ],
        "convergence": sel.convergence,
        "dissent": sel.dissent,
        "executive_read": sel.executive_read,
        "insights": insights,
        "clusters": clusters,
        "signals": signals,
        "spread": _slot_to_dict(sel.spread),
        "yolo": _slot_to_dict(sel.yolo),
        "rejected": [
            {"name": r.get("name", "?"), "reason": r.get("reason", ""), "detail": r.get("detail", "")}
            for r in sel.rejected[:8]
        ],
        "model_primary": sel.model_primary,
        "model_validator": sel.model_validator,
    }
