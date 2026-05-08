import type { Slot, SlotKey } from "../types";
import {
  daysToExpiry,
  directionPillClass,
  dteLabel,
  fmtRr,
  fmtUsd,
  structureLabel,
} from "../format";

const SLOT_LABELS: Record<SlotKey, string> = {
  spread: "Defined-risk spread",
  yolo: "YOLO long",
};

interface Props {
  slot: SlotKey;
  data: Slot;
  onLearnMore: (slot: SlotKey) => void;
}

export function TradeCard({ slot, data, onLearnMore }: Props) {
  const trade = data.trade;
  if (!trade) {
    return (
      <div className="trade-card is-empty">
        <div>
          <div className="trade-slot">{SLOT_LABELS[slot]}</div>
          <h3 className="trade-name">No trade this run</h3>
        </div>
        <div className="no-trade">
          <div className="reason">{data.no_trade_reason ?? "—"}</div>
          <div className="detail">{data.detail || "Conditions did not meet the bar."}</div>
        </div>
      </div>
    );
  }

  const dte = daysToExpiry(trade.expiration);
  const dteUrgent = dte <= 3;

  return (
    <article className="trade-card">
      <header className="trade-card-header">
        <div>
          <div className="trade-slot">{SLOT_LABELS[slot]}</div>
          <h3 className="trade-name">{trade.name}</h3>
          <div className="trade-meta">
            <span className={directionPillClass(trade.direction)}>
              <span className="dot" />
              {trade.direction.replace("_", " ")}
            </span>
            <span className="pill">
              <span className="dot" />
              {trade.root}
            </span>
            <span className="pill">{structureLabel(trade.structure)}</span>
            <span
              className={`pill ${dteUrgent ? "warn" : ""}`}
              title={`Holding window through expiration on ${trade.expiration}`}
            >
              <span className="dot" />
              hold {dteLabel(dte)}
            </span>
          </div>
        </div>
      </header>

      <div className="trade-stats">
        <div>
          <div className="stat-label">R / R</div>
          <div className="stat-value bull">{fmtRr(trade.rr_ratio)}</div>
        </div>
        <div>
          <div className="stat-label">Max loss</div>
          <div className="stat-value bear">{fmtUsd(trade.max_loss)}</div>
        </div>
        <div>
          <div className="stat-label">Max profit</div>
          <div className="stat-value bull">{fmtUsd(trade.max_profit)}</div>
        </div>
      </div>

      <p className="trade-catalyst">
        <strong>Catalyst.</strong> {trade.catalyst || "—"}
      </p>

      <div className="trade-card-footer">
        <span className="pill">
          {trade.suggested_contracts ?? "?"} ct · {fmtUsd(trade.risk_dollars)} risk
        </span>
        <button className="learn-more" onClick={() => onLearnMore(slot)}>
          Learn more
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M5 12h14M13 5l7 7-7 7" />
          </svg>
        </button>
      </div>
    </article>
  );
}
