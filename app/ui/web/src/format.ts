export const fmtUsd = (n: number | null | undefined): string => {
  if (n == null) return "—";
  if (Math.abs(n) >= 1000) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  return `$${n.toFixed(2)}`;
};

export const fmtNum = (n: number | null | undefined, digits = 2): string => {
  if (n == null) return "—";
  return n.toFixed(digits);
};

export const fmtPct = (n: number | null | undefined): string => {
  if (n == null) return "—";
  return `${(n * 100).toFixed(1)}%`;
};

export const fmtRr = (n: number | null | undefined): string => {
  if (n == null) return "∞";
  return `${n.toFixed(2)}×`;
};

const REGIME_LABELS: Record<string, string> = {
  liquidity_expansion: "Liquidity expansion",
  liquidity_withdrawal: "Liquidity withdrawal",
  inflation_scare: "Inflation scare",
  growth_scare: "Growth scare",
  policy_mistake: "Policy mistake",
  credit_stress: "Credit stress",
  geopolitical_shock: "Geopolitical shock",
  risk_on_meltup: "Risk-on melt-up",
  risk_off_deleveraging: "Risk-off deleveraging",
  no_signal: "No signal",
  conflicted: "Conflicted",
};

export const regimeLabel = (r: string): string => REGIME_LABELS[r] ?? r;

export const directionPillClass = (d: string): string => {
  if (d === "bullish") return "pill bull";
  if (d === "bearish") return "pill bear";
  if (d === "long_vol") return "pill vol";
  if (d === "short_vol") return "pill warn";
  return "pill";
};

export const regimePillClass = (r: string): string => {
  if (r === "liquidity_expansion" || r === "risk_on_meltup") return "pill bull";
  if (r === "liquidity_withdrawal" || r === "risk_off_deleveraging" || r === "credit_stress")
    return "pill bear";
  if (r === "inflation_scare" || r === "policy_mistake" || r === "geopolitical_shock")
    return "pill warn";
  if (r === "no_signal" || r === "conflicted") return "pill";
  return "pill";
};

export const structureLabel = (s: string): string =>
  s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const fmtRelativeTime = (iso: string): string => {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const sec = Math.round((now - then) / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
};

export const daysToExpiry = (expiration: string): number => {
  // expiration is a YYYY-MM-DD string from the server. Use UTC midnights so
  // local timezone doesn't shift the count.
  const exp = new Date(`${expiration}T00:00:00Z`).getTime();
  const today = new Date();
  const todayUtc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.max(0, Math.round((exp - todayUtc) / 86400_000));
};

export const dteLabel = (days: number): string => {
  if (days === 0) return "0d (today)";
  if (days === 1) return "1d";
  return `${days}d`;
};
