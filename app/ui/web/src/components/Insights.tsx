import { useMemo, useState } from "react";
import type { Impact, IndexQuote, Insight } from "../types";
import { useSnapshot } from "../useSnapshot";

interface Props {
  insights: Insight[];
}

const IMPACT_RANK: Record<Impact, number> = { XL: 4, L: 3, M: 2, S: 1 };

const fmtPct = (n: number | null | undefined): string => {
  if (n == null) return "—";
  const v = n * 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
};

const trendClass = (n: number | null | undefined): string => {
  if (n == null) return "trend-flat";
  if (Math.abs(n) < 1e-4) return "trend-flat";
  return n > 0 ? "trend-up" : "trend-down";
};

export function Insights({ insights }: Props) {
  const [showAll, setShowAll] = useState(false);
  const snap = useSnapshot();
  const quotesByLabel = useMemo(() => {
    const m = new Map<string, IndexQuote>();
    for (const q of snap?.quotes ?? []) m.set(q.label, q);
    return m;
  }, [snap]);

  const sorted = [...insights].sort(
    (a, b) => IMPACT_RANK[b.impact] - IMPACT_RANK[a.impact] || b.score - a.score,
  );
  const big = sorted.filter((i) => i.impact === "L" || i.impact === "XL");
  const rest = sorted.filter((i) => i.impact !== "L" && i.impact !== "XL");
  const visible = showAll ? sorted : big.length > 0 ? big : sorted.slice(0, 3);

  if (sorted.length === 0) {
    return (
      <p className="hero-sub">
        No headline-driven catalysts today. The brief still produces trade ideas if the regime
        warrants — see below.
      </p>
    );
  }

  return (
    <div className="insights">
      <ul className="insight-list">
        {visible.map((it, i) => {
          const etf = it.etf_label ? quotesByLabel.get(it.etf_label) : undefined;
          const pct2d = etf?.change_2d_pct ?? null;
          return (
            <li key={i} className={`insight insight-${it.impact}`}>
              <span className={`impact-badge impact-${it.impact}`} aria-label={`${it.impact} impact`}>
                {it.impact}
              </span>
              <span className="insight-text">
                <span className="insight-channel">{it.channel.replace(/_/g, " ")}</span>
                <span className="insight-line">{it.text}</span>
              </span>
              {it.etf_label && (
                <span className="insight-etf" title={`Most-impacted ETF · trailing 2 trading days`}>
                  <span className="insight-etf-label">{it.etf_label}</span>
                  <span className={`insight-etf-pct ${trendClass(pct2d)}`}>{fmtPct(pct2d)}</span>
                  <span className="insight-etf-period">2d</span>
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {!showAll && rest.length > 0 && big.length > 0 && (
        <button className="insight-toggle" onClick={() => setShowAll(true)}>
          + {rest.length} more {rest.length === 1 ? "insight" : "insights"} (M / S)
        </button>
      )}
      {showAll && rest.length > 0 && (
        <button className="insight-toggle" onClick={() => setShowAll(false)}>
          Show only L / XL
        </button>
      )}
    </div>
  );
}
