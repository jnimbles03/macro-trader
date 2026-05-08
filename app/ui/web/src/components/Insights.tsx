import { useState } from "react";
import type { Impact, Insight } from "../types";

interface Props {
  insights: Insight[];
}

const IMPACT_RANK: Record<Impact, number> = { XL: 4, L: 3, M: 2, S: 1 };

export function Insights({ insights }: Props) {
  const [showAll, setShowAll] = useState(false);

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
        {visible.map((it, i) => (
          <li key={i} className={`insight insight-${it.impact}`}>
            <span className={`impact-badge impact-${it.impact}`} aria-label={`${it.impact} impact`}>
              {it.impact}
            </span>
            <span className="insight-text">
              <span className="insight-channel">{it.channel.replace(/_/g, " ")}</span>
              <span className="insight-line">{it.text}</span>
            </span>
          </li>
        ))}
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
