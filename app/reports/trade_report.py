"""Top-level orchestrator that turns a SelectorOutput into a final report blob."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.analysis.causal_engine import run_causal_engine
from app.analysis.headline_classifier import (
    cluster_by_channel,
    dedupe,
    score_clusters,
)
from app.analysis.persona_weights import (
    convergence_dissent,
    top_personas,
    weight_personas,
)
from app.analysis.regime_detector import detect_regime
from app.analysis.trade_selector import SelectorOutput, select_trades
from app.config import get_settings
from app.data.market_data import get_market_tape
from app.data.news_ingest import fetch_recent_headlines
from app.data.option_chain import fetch_chains_for_candidates
from app.models.headline import Headline, HeadlineCluster
from app.models.macro_signal import MacroSignal, RegimeAssessment


@dataclass
class TradeBrief:
    generated_at: datetime
    headlines: list[Headline]
    clusters: list[HeadlineCluster]
    signals: list[MacroSignal]
    regime: RegimeAssessment
    persona_top: list[tuple[str, float, str]]
    selector: SelectorOutput


def generate_trade_brief(*,
                         lookback_hours: int = 24,
                         market_filter: str | None = None,
                         risk_profile: str | None = None,
                         fresh: bool = False) -> TradeBrief:
    s = get_settings()

    # 1-2. headlines + dedupe
    raw = fetch_recent_headlines(lookback_hours=lookback_hours, fresh=fresh)
    headlines = dedupe(raw)

    # 3. cluster + score
    clusters = score_clusters(cluster_by_channel(headlines))

    # macro tape
    tape = get_market_tape()
    signals = [MacroSignal(**sd) for sd in tape.get("signals", [])]

    # 4. regime + persona weights
    regime = detect_regime(clusters, signals)
    weights = weight_personas(regime.regime)
    convergence, dissent = convergence_dissent(regime.regime)
    regime.persona_weights = weights
    regime.convergence = convergence
    regime.dissent = dissent

    # 5-6. causal engine (Grok primary)
    causal = run_causal_engine(regime, clusters, chain_snapshots=[], market_tape=tape)

    # filter candidates by --market filter
    cands = causal.candidate_trades or []
    if market_filter:
        wanted_roots = _roots_for_market(market_filter)
        cands = [c for c in cands if (c.get("root") or "").upper() in wanted_roots]

    # 7. fetch chains
    chains = fetch_chains_for_candidates(cands, fresh=fresh)

    # 8. select trades + Opus validation
    sel = select_trades(
        regime=regime,
        clusters=clusters,
        chains_by_root=chains,
        candidate_trades=cands,
        model_primary=causal.model_used,
        executive_read=causal.executive_read,
        convergence=causal.convergence or convergence,
        dissent=causal.dissent or dissent,
    )

    return TradeBrief(
        generated_at=datetime.now(timezone.utc),
        headlines=headlines,
        clusters=clusters,
        signals=signals,
        regime=regime,
        persona_top=top_personas(regime.regime, n=4),
        selector=sel,
    )


def _roots_for_market(market: str) -> set[str]:
    market = market.lower()
    if market == "rates":
        return {"ZT", "ZF", "ZN", "TN", "ZB", "UB"}
    if market == "equity":
        return {"ES", "NQ", "RTY"}
    if market == "commodities":
        return {"CL", "NG", "GC", "SI", "HG"}
    if market == "fx":
        return {"6E", "6J", "6B", "6A", "6C", "6S"}
    return set()
