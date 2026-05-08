import { useEffect, useState } from "react";
import type { IndexQuote, SnapshotPayload } from "../types";

const REFRESH_MS = 30_000;

const fmtPrice = (n: number | null, kind: IndexQuote["kind"]): string => {
  if (n == null) return "—";
  const digits = kind === "future" ? 3 : n >= 1000 ? 2 : 2;
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

const fmtPct = (n: number | null): string => {
  if (n == null) return "—";
  const v = n * 100;
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
};

const trendClass = (n: number | null): string => {
  if (n == null || Math.abs(n) < 1e-6) return "trend-flat";
  return n > 0 ? "trend-up" : "trend-down";
};

export function IndexPanel() {
  const [data, setData] = useState<SnapshotPayload | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch("/api/snapshot");
        const json: SnapshotPayload = await res.json();
        if (!cancelled) setData(json);
      } catch {
        // keep last data; the panel just shows stale state
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <aside className="index-panel">
      <header className="index-panel-head">
        <div>
          <div className="index-panel-eyebrow">Markets</div>
          <div className="index-panel-title">Daily change</div>
        </div>
        <div className="index-panel-status">
          {data?.stale ? (
            <span className="status-dot status-dot-warn" title={data.gateway_error ?? "stale"} />
          ) : (
            <span className="status-dot status-dot-ok" />
          )}
          <span>
            {loading && !data
              ? "loading"
              : data?.mock
              ? "mock"
              : data?.stale
              ? "stale"
              : "live"}
          </span>
        </div>
      </header>

      <ul className="index-list">
        {(data?.quotes ?? []).map((q) => (
          <li key={q.label} className="index-row">
            <span className="index-label">{q.label}</span>
            <span className="index-price">{fmtPrice(q.last, q.kind)}</span>
            <span className={`index-change ${trendClass(q.change_pct)}`}>{fmtPct(q.change_pct)}</span>
          </li>
        ))}
        {!data?.quotes.length && !loading && (
          <li className="index-empty">
            {data?.gateway_error ? `Gateway: ${data.gateway_error}` : "No data"}
          </li>
        )}
      </ul>

      {data && (
        <div className="index-panel-foot">
          {data.mock ? "synthetic" : `updated ${Math.round(data.age_seconds)}s ago`}
        </div>
      )}
    </aside>
  );
}
