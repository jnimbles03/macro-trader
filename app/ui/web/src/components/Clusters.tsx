import type { Cluster } from "../types";
import { fmtRelativeTime } from "../format";

interface Props {
  clusters: Cluster[];
}

export function Clusters({ clusters }: Props) {
  if (clusters.length === 0) return null;
  return (
    <section className="section">
      <div className="section-head">
        <h2 className="section-title">Top headline clusters</h2>
        <span className="section-count">{clusters.length} shown</span>
      </div>
      <div className="clusters">
        {clusters.map((c) => (
          <details key={c.name} className="cluster">
            <summary>
              <h3 className="cluster-title">{c.name}</h3>
              <div className="cluster-meta">
                <span>{c.channel.replace(/_/g, " ")}</span>
                <span>·</span>
                <span>{c.best_tier.replace("_", " ")}</span>
                <span>·</span>
                <span className="cluster-score">score {c.composite_score.toFixed(2)}</span>
              </div>
            </summary>
            <div className="cluster-body">
              {c.summary && <p className="cluster-summary">{c.summary}</p>}
              <ul className="headline-list">
                {c.headlines.map((h, i) => (
                  <li key={i}>
                    <a href={h.url} target="_blank" rel="noopener noreferrer">
                      {h.title}
                    </a>
                    <span className="headline-source">
                      {h.source} · {h.tier.replace("_", " ")} · {fmtRelativeTime(h.published_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}
