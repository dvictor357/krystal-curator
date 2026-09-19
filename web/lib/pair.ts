import type { Pool } from "./types";

const PROTOCOLS: Record<string, string> = {
  uniswapv2: "Uniswap v2",
  uniswapv3: "Uniswap v3",
  uniswapv4: "Uniswap v4",
  ramsescl: "Ramses CL",
};

const TONES: Record<string, string> = {
  USDG: "tone-stable",
  USDC: "tone-stable",
  USDT: "tone-stable",
  DAI: "tone-stable",
  WETH: "tone-eth",
  ETH: "tone-eth",
  WBTC: "tone-btc",
  BTC: "tone-btc",
};

export function splitPair(
  pool: Pick<Pool, "pair" | "token0" | "token1">,
): [string, string] {
  if (pool.token0 && pool.token1) return [pool.token0, pool.token1];
  const [left, right] = pool.pair.split("/");
  return [left || "?", right || "?"];
}

export function protocolLabel(protocol: string) {
  return PROTOCOLS[protocol] || protocol.replace(/v(\d+)$/i, " v$1");
}

export function feeLabel(fee?: number) {
  if (fee == null || !Number.isFinite(fee) || fee <= 0) return "";
  const digits = fee >= 1 ? 2 : fee >= 0.1 ? 2 : 4;
  return `${fee.toFixed(digits).replace(/0+$/, "").replace(/\.$/, "")}%`;
}

export function tokenTone(symbol: string) {
  const key = symbol.toUpperCase();
  if (TONES[key]) return TONES[key];
  let hash = 0;
  for (const char of key) hash = (hash * 33 + char.charCodeAt(0)) >>> 0;
  return `tone-${hash % 4}`;
}

export function tokenGlyph(symbol: string) {
  const text = symbol.trim() || "?";
  return text.slice(0, 2).toUpperCase();
}

export function safeLogo(url?: string) {
  return url && /^https:\/\//i.test(url) ? url : "";
}

export function uniquePairs(rows: Pool[], limit = 6) {
  const out: Pool[] = [];
  const seen = new Set<string>();
  for (const pool of rows) {
    const [token0, token1] = splitPair(pool);
    const key = `${token0}/${token1}:${pool.protocol}:${pool.feeTier ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(pool);
    if (out.length >= limit) break;
  }
  return out;
}
