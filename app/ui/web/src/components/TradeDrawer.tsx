import { useEffect } from "react";
import type { Trade } from "../types";
import { daysToExpiry, dteLabel, fmtNum, fmtPct, fmtRr, fmtUsd, structureLabel } from "../format";

interface Props {
  trade: Trade;
  onClose: () => void;
}

export function TradeDrawer({ trade, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const v = trade.validator_verdict;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true">
        <header className="drawer-header">
          <div>
            <div className="trade-slot">{structureLabel(trade.structure)}</div>
            <h2 className="trade-name" style={{ fontSize: 24, marginTop: 6 }}>
              {trade.name}
            </h2>
            <div className="trade-meta">
              <span className="pill">{trade.root}</span>
              <span className="pill">exp {trade.expiration}</span>
              <span className="pill">hold {dteLabel(daysToExpiry(trade.expiration))} max</span>
              <span className="pill">R/R {fmtRr(trade.rr_ratio)}</span>
              {trade.expected_move_pct != null && (
                <span className="pill">expected move {fmtPct(trade.expected_move_pct)}</span>
              )}
            </div>
          </div>
          <button className="drawer-close" onClick={onClose} aria-label="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </header>

        <div className="drawer-body">
          <section className="drawer-section">
            <h4>Causal chain</h4>
            <p>{trade.causal_chain || "—"}</p>
          </section>

          <section className="drawer-section">
            <h4>Why this structure</h4>
            <p>{trade.why_this_structure || "—"}</p>
          </section>

          <section className="drawer-section">
            <h4>Legs</h4>
            <table className="legs-table">
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Qty</th>
                  <th>Type</th>
                  <th>Strike</th>
                  <th>Premium</th>
                  <th>Δ</th>
                  <th>Γ</th>
                  <th>Θ</th>
                  <th>ν</th>
                  <th>IV</th>
                </tr>
              </thead>
              <tbody>
                {trade.legs.map((l, i) => (
                  <tr key={i}>
                    <td className={l.action === "BUY" ? "action-buy" : "action-sell"}>{l.action}</td>
                    <td>{l.quantity}</td>
                    <td>{l.option_type}</td>
                    <td>{l.strike}</td>
                    <td>{fmtNum(l.premium, 4)}</td>
                    <td>{fmtNum(l.delta, 2)}</td>
                    <td>{fmtNum(l.gamma, 4)}</td>
                    <td>{fmtNum(l.theta, 4)}</td>
                    <td>{fmtNum(l.vega, 3)}</td>
                    <td>{fmtNum(l.iv, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="drawer-section">
            <h4>Math</h4>
            <p className="muted">
              Entry {fmtNum(trade.entry_debit_credit, 4)} · Max loss {fmtUsd(trade.max_loss)} · Max profit{" "}
              {fmtUsd(trade.max_profit)} · Breakeven {trade.breakeven.map((b) => b.toFixed(2)).join(", ")}
            </p>
          </section>

          <section className="drawer-section">
            <h4>What kills the thesis</h4>
            <p>{trade.what_kills_thesis || "—"}</p>
          </section>

          {trade.why_probably_dumb && (
            <section className="drawer-section">
              <h4>Why this is probably dumb</h4>
              <p>{trade.why_probably_dumb}</p>
            </section>
          )}

          <section className="drawer-section">
            <h4>Risk plan</h4>
            <p className="muted">
              <strong>Invalidation.</strong> {trade.invalidation || "—"}
            </p>
            <p className="muted" style={{ marginTop: 8 }}>
              <strong>Stop.</strong> {trade.stop_logic || "—"}
            </p>
            <p className="muted" style={{ marginTop: 8 }}>
              <strong>Profit-taking.</strong> {trade.profit_taking_logic || "—"}
            </p>
          </section>

          <section className="drawer-section">
            <h4>Sizing</h4>
            <p>
              {trade.suggested_contracts ?? "?"} contracts · {fmtUsd(trade.risk_dollars)} risk
            </p>
            {trade.sizing_note && <p className="muted" style={{ marginTop: 6 }}>{trade.sizing_note}</p>}
          </section>

          {v && (
            <section className="verdict">
              <div className="verdict-head">
                <h4>Validator: {v.decision.toUpperCase()}</h4>
                <span className="verdict-conf">confidence {v.confidence.toFixed(2)}</span>
              </div>
              <div className="verdict-grid">
                <div>
                  <span>News</span>
                  {v.news_check}
                </div>
                <div>
                  <span>Trade theory</span>
                  {v.trade_theory_check}
                </div>
                <div>
                  <span>Risk / reward</span>
                  {v.risk_reward_check}
                </div>
                <div>
                  <span>Option strategy</span>
                  {v.option_strategy_check}
                </div>
              </div>
              {v.issues.length > 0 && (
                <div className="verdict-issues">{v.issues.join(" · ")}</div>
              )}
            </section>
          )}
        </div>
      </aside>
    </>
  );
}
