export const profiles = [
  "conservative",
  "balanced",
  "aggressive",
  "degen",
] as const;
/** Chains the Krystal feed serves pools for (Ronin returns none). */
export const chains = {
  4663: "Robinhood",
  1: "Ethereum",
  8453: "Base",
  42161: "Arbitrum",
  10: "Optimism",
  56: "BNB Chain",
  137: "Polygon",
  999: "HyperEVM",
  43114: "Avalanche",
} as const;
/** Quote chips per chain, most common first (Krystal top-200 by TVL); "" = any. */
export const quotesFor = (chain: number): [string, string][] => {
  const q: Record<number, string[]> = {
    4663: ["USDG", "USDC", "USDT", "WETH"],
    1: ["WETH", "USDC", "USDT"],
    8453: ["USDC", "WETH", "CBBTC"],
    42161: ["USDC", "WETH", "USD₮0", "ARB"],
    10: ["USDC", "WETH", "USDT"],
    56: ["USDT", "WBNB", "ETH"],
    137: ["USDC", "USDT0", "WETH", "WPOL"],
    999: ["WHYPE", "USD₮0", "USDC"],
    43114: ["USDC", "WAVAX", "USDT"],
  };
  return [
    ...(q[chain] ?? ["USDC", "WETH"]).map((s) => [s, s] as [string, string]),
    ["", "Any"],
  ];
};
export const defaultQuote = (chain: number) => quotesFor(chain)[0][0];
export function validSettings(value: Record<string, unknown>) {
  return (
    profiles.includes(value.profile as (typeof profiles)[number]) &&
    typeof value.chain === "number" &&
    value.chain in chains &&
    value.source === "krystal" &&
    typeof value.size === "number" &&
    Number.isFinite(value.size) &&
    value.size >= 1 &&
    value.size <= 100_000_000 &&
    typeof value.wallet === "string" &&
    (value.wallet === "" || /^0x[a-fA-F0-9]{40}$/.test(value.wallet))
  );
}
export function validPoolId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 180 &&
    /^\d+:[a-zA-Z0-9_-]+:0x[a-fA-F0-9]{40}(?:[a-fA-F0-9]{24})?$/.test(value)
  );
}
