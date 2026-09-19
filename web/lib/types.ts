export type Settings = {
  profile: string;
  chain: number;
  source: string;
  size: number;
  wallet: string;
  telegram_chat_id: string;
  alerts: boolean;
};
export type Pool = {
  id: string;
  pair: string;
  token0?: string;
  token1?: string;
  feeTier?: number;
  token0Address?: string;
  token1Address?: string;
  token0Logo?: string;
  token1Logo?: string;
  address: string;
  chain: number;
  protocol: string;
  source: string;
  url: string;
  tvl: number;
  volume: number;
  fees: number;
  feeYield: number;
  volatility: number | null;
  drawdown: number | null;
  score: number;
  grade: string;
  flags: string[];
  parts: Record<string, number>;
  unknown: string[];
  risks: string[];
  tvlBasis: string;
  sim: Record<string, number | null>;
};
export const money = (value: number | null | undefined, compact = false) =>
  value == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: compact ? 1 : 2,
        notation: compact ? "compact" : "standard",
      }).format(value);
export const pct = (value: number | null | undefined) =>
  value == null ? "Unknown" : `${value.toFixed(2)}%`;
export const defaults: Settings = {
  profile: "balanced",
  chain: 4663,
  source: "krystal",
  size: 10000,
  wallet: "",
  telegram_chat_id: "",
  alerts: true,
};
