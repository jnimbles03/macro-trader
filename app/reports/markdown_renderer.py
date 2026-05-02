"""Markdown rendering of the trade brief."""

from __future__ import annotations

from app.analysis.persona_weights import PERSONAS
from app.models.trade_idea import TradeIdea, TradeKind
from app.reports.trade_report import TradeBrief

DISCLAIMER = "Mode: Paper research only — not financial advice. Human review required before any execution."


def _fmt_legs(trade: TradeIdea) -> str:
    lines = []
    for l in trade.legs:
        sign = "+" if l.action == "BUY" else "-"
        lines.append(f"    {sign}{l.quantity} {l.option_type.value} {l.strike:g} @ {l.premium:.4f} "
                     f"(δ {l.delta:+.2f}, γ {l.gamma:.4f}, θ {l.theta:.4f}, ν {l.vega:.3f}, IV {l.iv:.3f})")
    return "\n".join(lines)


def _fmt_trade(trade: TradeIdea, slot: str) -> str:
    rr = f"{trade.rr_ratio:.2f}" if trade.rr_ratio < 1e6 else "∞"
    be = ", ".join(f"{b:.4f}" for b in trade.breakeven)
    sizing_line = trade.sizing_note or ""
    if trade.suggested_contracts and trade.suggested_contracts > 0:
        sizing_line = f"{trade.suggested_contracts} contracts (${trade.risk_dollars:.2f} risk) — {sizing_line}"
    yolo_dumb = ""
    if trade.kind == TradeKind.YOLO_LONG and trade.why_probably_dumb:
        yolo_dumb = f"\n**Why this is probably dumb:** {trade.why_probably_dumb}"

    validator_block = ""
    if trade.validator_verdict is not None:
        v = trade.validator_verdict
        validator_block = (
            f"\n**Opus validator:** {v.decision.upper()} (confidence {v.confidence:.2f})\n"
            f"  - News: {v.news_check}\n"
            f"  - Trade theory: {v.trade_theory_check}\n"
            f"  - Risk/reward: {v.risk_reward_check}\n"
            f"  - Option strategy: {v.option_strategy_check}\n"
        )
        if v.issues:
            validator_block += "  - Issues: " + "; ".join(v.issues) + "\n"

    return f"""## Trade {slot} — {trade.name}

- Market: {trade.root}  ({trade.underlying_symbol})
- Direction: {trade.direction}
- Structure: {trade.structure.value}
- Expiration: {trade.expiration}
- Legs:
{_fmt_legs(trade)}
- Entry debit/credit (price units): {trade.entry_debit_credit:+.4f}
- Max loss: ${trade.max_loss:.2f}
- Max profit: ${trade.max_profit:.2f}
- max_gain ÷ max_loss: **{rr}**
- Breakeven: {be}
- Worst bid/ask %: {trade.bid_ask_pct_worst:.3f} | min volume: {trade.min_volume} | min OI: {trade.min_open_interest}
- Catalyst: {trade.catalyst}

**Causal chain:** {trade.causal_chain}

**Why this structure:** {trade.why_this_structure}

**What kills the thesis:** {trade.what_kills_thesis}{yolo_dumb}

- Invalidation: {trade.invalidation}
- Stop logic: {trade.stop_logic}
- Profit-taking logic: {trade.profit_taking_logic}
- Suggested size: {sizing_line}
{validator_block}"""


def render_brief(brief: TradeBrief) -> str:
    sel = brief.selector
    parts: list[str] = []
    parts.append(f"# Macro Options Scout — 24h Trade Brief")
    parts.append(f"Generated: {brief.generated_at.isoformat()}")
    parts.append(DISCLAIMER)
    parts.append("")

    # Executive Read
    parts.append("## Executive Read")
    if sel.executive_read:
        parts.extend(f"- {b}" for b in sel.executive_read)
    else:
        parts.append("- (no executive bullets)")
    parts.append("")

    # Regime
    parts.append("## Dominant Macro Regime")
    parts.append(f"**{brief.regime.regime.value}** (confidence {brief.regime.confidence:.2f}) — {brief.regime.explanation}")
    parts.append("")

    # Persona weights
    parts.append("## Persona Weights (this run)")
    for name, w, lens in brief.persona_top:
        parts.append(f"- **{name}** ({w:.2f}) — {lens}")
    if sel.convergence:
        parts.append(f"\nConvergence: {', '.join(sel.convergence)}")
    if sel.dissent:
        parts.append(f"Dissent: {', '.join(sel.dissent)}")
    parts.append("")

    # Top headline clusters
    parts.append("## Top Headline Clusters")
    ranked = sorted(brief.clusters, key=lambda c: c.composite_score, reverse=True)[:5]
    for c in ranked:
        parts.append(f"### {c.name}")
        parts.append(f"Channel: {c.channel}; best tier: {c.best_tier.value}; composite score: {c.composite_score:.2f}")
        sources = "; ".join(f"{h.source} ({h.tier.value})" for h in c.headlines[:3])
        parts.append(f"Key sources: {sources}")
        parts.append(f"Summary: {c.summary}")
        parts.append("")

    # Trade 1 / spread
    parts.append("## Trade 1 — Defined-Risk Spread")
    if sel.spread.trade is not None:
        parts.append(_fmt_trade(sel.spread.trade, "1"))
    else:
        parts.append(f"**NO TRADE** — {sel.spread.no_trade_reason.value if sel.spread.no_trade_reason else 'unknown'}: {sel.spread.detail}")
    parts.append("")

    # Trade 2 / yolo
    parts.append("## Trade 2 — YOLO Futures Option")
    if sel.yolo.trade is not None:
        parts.append(_fmt_trade(sel.yolo.trade, "2"))
    else:
        parts.append(f"**NO TRADE** — {sel.yolo.no_trade_reason.value if sel.yolo.no_trade_reason else 'unknown'}: {sel.yolo.detail}")
    parts.append("")

    # Rejected trades
    parts.append("## Rejected Trades")
    if sel.rejected:
        for r in sel.rejected[:6]:
            parts.append(f"- {r.get('name', '?')} — {r.get('reason')}: {r.get('detail', '')}")
    else:
        parts.append("- (none)")
    parts.append("")

    # Final human checklist
    parts.append("## Final Human Checklist")
    parts.extend([
        "- Are quotes live and bid/ask within per-asset threshold?",
        "- Is the catalyst still in play, or has it been priced?",
        "- Any economic release scheduled before expiration that could whipsaw?",
        "- Sized to lose completely — could you take a 100% loss without flinching?",
        "- Has the thesis changed since the brief was generated?",
    ])

    parts.append("")
    parts.append(f"*Primary model:* {sel.model_primary}  |  *Validator:* {sel.model_validator}")
    parts.append(f"*Personas in repo:* {', '.join(sorted(PERSONAS.keys()))}")
    return "\n".join(parts)
