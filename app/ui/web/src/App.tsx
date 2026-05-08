import { useCallback, useEffect, useState } from "react";
import type { Brief, SlotKey } from "./types";
import { fmtRelativeTime, regimeLabel, regimePillClass } from "./format";
import { TradeCard } from "./components/TradeCard";
import { TradeDrawer } from "./components/TradeDrawer";
import { RegimePanel } from "./components/RegimePanel";
import { Clusters } from "./components/Clusters";
import { IndexPanel } from "./components/IndexPanel";

interface ControlsState {
  lookback: number;
  market: string;
  fresh: boolean;
}

const MARKETS = [
  { value: "", label: "All markets" },
  { value: "rates", label: "Rates" },
  { value: "equity", label: "Equity" },
  { value: "commodities", label: "Commodities" },
  { value: "fx", label: "FX" },
];

export function App() {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openSlot, setOpenSlot] = useState<SlotKey | null>(null);
  const [controls, setControls] = useState<ControlsState>({
    lookback: 24,
    market: "",
    fresh: false,
  });

  const fetchBrief = useCallback(async (c: ControlsState) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        lookback: String(c.lookback),
        market: c.market,
        fresh: String(c.fresh),
      });
      const res = await fetch(`/api/brief?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Brief = await res.json();
      setBrief(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load brief");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBrief(controls);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onPoke = (e: React.FormEvent) => {
    e.preventDefault();
    fetchBrief(controls);
  };

  const openTrade = openSlot && brief ? brief[openSlot].trade : null;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" />
          <div>
            <div className="brand-title">Macro Options Scout</div>
            <div className="brand-sub">Research only · never financial advice</div>
          </div>
        </div>
        <form className="controls" onSubmit={onPoke}>
          <input
            type="number"
            min={1}
            max={168}
            value={controls.lookback}
            onChange={(e) => setControls({ ...controls, lookback: Number(e.target.value) })}
            title="Lookback hours"
          />
          <select
            value={controls.market}
            onChange={(e) => setControls({ ...controls, market: e.target.value })}
          >
            {MARKETS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
          <label
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 13,
              color: "var(--text-dim)",
            }}
          >
            <input
              type="checkbox"
              checked={controls.fresh}
              onChange={(e) => setControls({ ...controls, fresh: e.target.checked })}
            />
            fresh
          </label>
          <button className="primary" type="submit" disabled={loading}>
            {loading ? "Working…" : "Refresh"}
          </button>
        </form>
      </header>

      {loading && !brief && (
        <div className="loading">
          <div className="spinner" />
          Generating brief…
        </div>
      )}

      {error && (
        <div className="error-box">Could not load the brief: {error}</div>
      )}

      {brief && (
        <>
          <div className="hero">
            <div className="hero-text">
              <div className="hero-eyebrow">Today's brief</div>
              <h1 className="hero-title">
                What the macro tape is paying for
                <br />
                in the next 24 hours.
              </h1>
              <p className="hero-sub">
                Two trade ideas — one defined-risk spread, one convex YOLO — built from a Grok
                primary synthesis and an Opus adversarial review. Everything else on this page is
                the evidence.
              </p>

              <div className="regime-row">
                <span className={regimePillClass(brief.regime.regime)}>
                  <span className="dot" />
                  {regimeLabel(brief.regime.regime)}
                </span>
                <span className="pill">
                  <span className="dot" />
                  confidence {brief.regime.confidence.toFixed(2)}
                </span>
                <span className="pill">{fmtRelativeTime(brief.generated_at)}</span>
              </div>
            </div>
            <IndexPanel />
          </div>

          <div className="trade-grid">
            <TradeCard slot="spread" data={brief.spread} onLearnMore={setOpenSlot} />
            <TradeCard slot="yolo" data={brief.yolo} onLearnMore={setOpenSlot} />
          </div>

          {brief.executive_read.length > 0 && (
            <section className="section">
              <div className="section-head">
                <h2 className="section-title">Executive read</h2>
                <span className="section-count">{brief.executive_read.length}</span>
              </div>
              <div className="exec-grid">
                {brief.executive_read.map((b, i) => (
                  <div key={i} className="exec-card">
                    {b}
                  </div>
                ))}
              </div>
            </section>
          )}

          <RegimePanel brief={brief} />

          <Clusters clusters={brief.clusters} />

          {brief.rejected.length > 0 && (
            <section className="section">
              <div className="section-head">
                <h2 className="section-title">Rejected ideas</h2>
                <span className="section-count">{brief.rejected.length}</span>
              </div>
              <div className="clusters">
                {brief.rejected.map((r, i) => (
                  <div key={i} className="cluster" style={{ padding: "16px 22px" }}>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 16,
                        flexWrap: "wrap",
                      }}
                    >
                      <strong>{r.name}</strong>
                      <span className="cluster-meta">
                        <span style={{ color: "var(--warn)" }}>{r.reason}</span>
                      </span>
                    </div>
                    {r.detail && (
                      <p className="cluster-summary" style={{ marginTop: 8 }}>
                        {r.detail}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          <footer className="footer">
            <div>
              Primary <strong style={{ color: "var(--text-dim)" }}>{brief.model_primary || "—"}</strong>
              {" · "}
              Validator <strong style={{ color: "var(--text-dim)" }}>{brief.model_validator || "—"}</strong>
            </div>
            <div>Generated {new Date(brief.generated_at).toLocaleString()}</div>
          </footer>
        </>
      )}

      {openTrade && <TradeDrawer trade={openTrade} onClose={() => setOpenSlot(null)} />}
    </div>
  );
}
