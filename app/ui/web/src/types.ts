export type ValidatorDecision = "accept" | "revise" | "reject";

export interface ValidatorVerdict {
  decision: ValidatorDecision;
  news_check: string;
  trade_theory_check: string;
  risk_reward_check: string;
  option_strategy_check: string;
  issues: string[];
  revisions_suggested: string[];
  confidence: number;
}

export interface TradeLeg {
  action: "BUY" | "SELL";
  quantity: number;
  option_type: "C" | "P";
  strike: number;
  expiration: string;
  premium: number;
  iv: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}

export interface Trade {
  kind: "defined_risk_spread" | "yolo_long";
  name: string;
  root: string;
  underlying_symbol: string;
  direction: "bullish" | "bearish" | "neutral" | "long_vol" | "short_vol";
  structure: string;
  expiration: string;
  legs: TradeLeg[];
  entry_debit_credit: number;
  max_loss: number;
  max_profit: number | null;
  rr_ratio: number | null;
  breakeven: number[];
  expected_move_pct: number | null;
  probability_itm: number | null;
  bid_ask_pct_worst: number;
  min_volume: number;
  min_open_interest: number;
  catalyst: string;
  causal_chain: string;
  why_this_structure: string;
  what_kills_thesis: string;
  why_probably_dumb: string | null;
  invalidation: string;
  stop_logic: string;
  profit_taking_logic: string;
  suggested_contracts: number | null;
  risk_dollars: number | null;
  sizing_note: string | null;
  validator_verdict: ValidatorVerdict | null;
}

export interface Slot {
  trade: Trade | null;
  no_trade_reason: string | null;
  detail: string;
}

export interface ClusterHeadline {
  title: string;
  source: string;
  tier: string;
  url: string;
  published_at: string;
}

export type Impact = "S" | "M" | "L" | "XL";

export interface Insight {
  impact: Impact;
  score: number;
  text: string;
  channel: string;
  cluster_name: string;
  etf_label: string | null;
}

export interface Cluster {
  name: string;
  channel: string;
  best_tier: string;
  composite_score: number;
  impact: Impact;
  summary: string;
  headlines: ClusterHeadline[];
}

export interface Persona {
  name: string;
  weight: number;
  lens: string;
}

export interface Signal {
  series_id: string;
  label: string;
  value: number;
  units: string | null;
  as_of: string;
  surprise_vs_consensus: number | null;
}

export interface Brief {
  generated_at: string;
  regime: { regime: string; confidence: number; explanation: string };
  personas: Persona[];
  convergence: string[];
  dissent: string[];
  executive_read: string[];
  insights: Insight[];
  clusters: Cluster[];
  signals: Signal[];
  spread: Slot;
  yolo: Slot;
  rejected: { name: string; reason: string; detail: string }[];
  model_primary: string;
  model_validator: string;
}

export type SlotKey = "spread" | "yolo";

export interface IndexQuote {
  label: string;
  kind: "stock" | "future" | "index";
  last: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  currency: string | null;
  change_2d_pct?: number | null;
  error?: string | null;
}

export interface SnapshotPayload {
  quotes: IndexQuote[];
  fetched_at: number;
  stale: boolean;
  gateway_error: string | null;
  age_seconds: number;
  mock?: boolean;
}
