import { useEffect, useMemo, useState } from "react";
import type { IndexQuote, SnapshotPayload } from "../types";

const REFRESH_MS = 30_000;

interface Bucket {
  name: string;
  labels: string[];
}

const BUCKETS: Bucket[] = [
  { name: "US equity", labels: ["SPY", "DIA", "QQQ"] },
  { name: "Treasuries", labels: ["SHY", "BND", "TLT", "MUB"] },
  { name: "Credit", labels: ["HYG"] },
  { name: "Rates futures", labels: ["ZN", "ZB"] },
  { name: "Volatility", labels: ["VIX"] },
  { name: "Global equity", labels: ["EEM", "FXI", "FTSE", "DAX"] },
];

const fmtPct = (n: number | null): string => {
  if (n == null) return "—";
  const v = n * 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
};

const fmtPrice = (q: IndexQuote | undefined): string => {
  if (!q || q.last == null) return "—";
  const digits = q.kind === "future" ? 3 : 2;
  return q.last.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

const trendClass = (n: number | null | undefined): string => {
  if (n == null) return "trend-flat";
  if (Math.abs(n) < 1e-4) return "trend-flat";
  return n > 0 ? "trend-up" : "trend-down";
};

export function MarketsPanel() {
  const [snap, setSnap] = useState<SnapshotPayload | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch("/api/snapshot");
        const json: SnapshotPayload = await res.json();
        if (!cancelled) setSnap(json);
      } catch {
        // keep last data
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

  const quotes = useMemo(() => {
    const m = new Map<string, IndexQuote>();
    for (const q of snap?.quotes ?? []) m.set(q.label, q);
    return m;
  }, [snap]);

  // Panel-wide normalization so the biggest mover anywhere sets the scale —
  // makes "where the action is" visible at a glance.
  const maxAbsPct = useMemo(() => {
    let m = 0;
    for (const q of snap?.quotes ?? []) {
      if (q.change_pct != null) m = Math.max(m, Math.abs(q.change_pct));
    }
    return m || 1e-6;
  }, [snap]);

  return (
    <aside className="markets-panel">
      <header className="markets-head">
        <div>
          <div className="markets-eyebrow">Markets</div>
          <div className="markets-title">Where the action is</div>
        </div>
        <div className="markets-status">
          {snap?.stale ? (
            <span className="status-dot status-dot-warn" title={snap.gateway_error ?? "stale"} />
          ) : (
            <span className="status-dot status-dot-ok" />
          )}
          <span>
            {loading && !snap
              ? "loading"
              : snap?.mock
              ? "mock"
              : snap?.stale
              ? "stale"
              : "live"}
          </span>
        </div>
      </header>

      <div className="markets-buckets">
        {BUCKETS.map((b) => {
          const rows = b.labels
            .map((label) => quotes.get(label))
            .filter((q): q is IndexQuote => !!q)
            .sort(
              (a, b) =>
                Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0),
            );
          if (rows.length === 0) return null;
          return (
            <section key={b.name} className="markets-bucket">
              <div className="markets-bucket-name">{b.name}</div>
              <ul className="markets-list">
                {rows.map((q) => {
                  const pct = q.change_pct;
                  const width =
                    pct == null ? 0 : Math.min(100, (Math.abs(pct) / maxAbsPct) * 100);
                  return (
                    <li key={q.label} className="markets-row">
                      <span className="markets-label">{q.label}</span>
                      <span className="markets-price">{fmtPrice(q)}</span>
                      <span className={`markets-pct ${trendClass(pct)}`}>{fmtPct(pct)}</span>
                      <span className="markets-bar-track" aria-hidden>
                        <span
                          className={`markets-bar ${trendClass(pct)}`}
                          style={{ width: `${width}%` }}
                        />
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>

      {snap && (
        <div className="markets-foot">
          {snap.mock ? "synthetic" : `updated ${Math.round(snap.age_seconds)}s ago`}
        </div>
      )}
    </aside>
  );
}
