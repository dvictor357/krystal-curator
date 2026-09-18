export const profiles = [
  "conservative",
  "balanced",
  "aggressive",
  "degen",
] as const;
export const chains = {
  4663: "Robinhood",
  1: "Ethereum",
  8453: "Base",
  42161: "Arbitrum",
  10: "Optimism",
  56: "BNB Chain",
  137: "Polygon",
  999: "HyperEVM",
  2020: "Ronin",
  43114: "Avalanche",
} as const;
export function validSettings(value: Record<string, unknown>) {
  return (
    profiles.includes(value.profile as (typeof profiles)[number]) &&
    typeof value.chain === "number" &&
    value.chain in chains &&
    (value.source === "krystal" ||
      (value.source === "rhpools" && value.chain === 4663)) &&
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
