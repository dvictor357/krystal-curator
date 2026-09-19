/** Where an address can be looked at, per chain. Explorer routes follow Blockscout/Etherscan. */
const explorers: Record<number, { name: string; base: string }> = {
  1: { name: "Etherscan", base: "https://etherscan.io" },
  10: { name: "Optimism Etherscan", base: "https://optimistic.etherscan.io" },
  56: { name: "BscScan", base: "https://bscscan.com" },
  137: { name: "Polygonscan", base: "https://polygonscan.com" },
  999: { name: "HyperEVM scan", base: "https://hyperevmscan.io" },
  2020: { name: "Ronin explorer", base: "https://app.roninchain.com" },
  4663: { name: "Robinscan", base: "https://robinscan.io" },
  8453: { name: "Basescan", base: "https://basescan.org" },
  42161: { name: "Arbiscan", base: "https://arbiscan.io" },
  43114: { name: "Snowtrace", base: "https://snowtrace.io" },
};
const dexChain: Record<number, string> = {
  1: "ethereum",
  10: "optimism",
  56: "bsc",
  137: "polygon",
  999: "hyperevm",
  2020: "ronin",
  4663: "robinhood",
  8453: "base",
  42161: "arbitrum",
  43114: "avalanche",
};

export type Action = {
  id: string;
  label: string;
  hint?: string;
  href?: string;
  copy?: string;
  run?: () => void | Promise<void>;
  kind: "copy" | "link" | "run";
  danger?: boolean;
};

export const KRYSTAL_REF = "35STGKW0";
/** Any defi.krystal.app link we hand out carries the referral code (idempotent). */
export function withRef(url: string) {
  try {
    const u = new URL(url);
    if (u.hostname.endsWith("krystal.app") && !u.searchParams.has("r"))
      u.searchParams.set("r", KRYSTAL_REF);
    return u.toString();
  } catch {
    return url;
  }
}

export const isAddress = (v: string) => /^0x[0-9a-fA-F]{40}$/.test(v);
export const shorten = (v: string) =>
  v.length > 14 ? `${v.slice(0, 8)}…${v.slice(-6)}` : v;

export function explorerName(chain: number) {
  return explorers[chain]?.name ?? "Explorer";
}

/** Actions for one address. `kind` decides which destinations make sense. */
export function addressActions(
  kind: "wallet" | "pool" | "token" | "vault",
  address: string,
  chain: number,
  extra: { krystalUrl?: string; symbol?: string; poolLabel?: string } = {},
): Action[] {
  const out: Action[] = [
    {
      id: "copy",
      kind: "copy",
      label: "Copy address",
      hint: shorten(address),
      copy: address,
    },
  ];
  const ex = explorers[chain];
  const dex = dexChain[chain];
  const plain = isAddress(address); // v4 pool ids are 32 bytes: no explorer page
  if (kind === "token" && ex && plain)
    out.push({
      id: "explorer",
      kind: "link",
      label: `Token on ${ex.name}`,
      hint: "holders · transfers · contract",
      href: `${ex.base}/token/${address}`,
    });
  else if (ex && plain)
    out.push({
      id: "explorer",
      kind: "link",
      label: `Open in ${ex.name}`,
      hint:
        kind === "wallet"
          ? "balances · transactions"
          : "contract · transactions",
      href: `${ex.base}/address/${address}`,
    });
  if (kind === "pool" && extra.krystalUrl)
    out.push({
      id: "krystal",
      kind: "link",
      label: "Open pool on Krystal",
      hint: "add liquidity · automation",
      href: withRef(extra.krystalUrl),
    });
  if (kind === "vault" && extra.krystalUrl)
    out.push({
      id: "krystal",
      kind: "link",
      label: "Open vault on Krystal",
      hint: "deposit · strategy · history",
      href: withRef(extra.krystalUrl),
    });
  if ((kind === "pool" || kind === "token") && dex)
    out.push({
      id: "dexscreener",
      kind: "link",
      label: `${kind === "token" ? "Token" : "Pair"} on DexScreener`,
      hint: "chart · trades · liquidity",
      href: plain
        ? `https://dexscreener.com/${dex}/${address}`
        : `https://dexscreener.com/search?q=${address}`,
    });
  if (kind === "token" && dex)
    out.push({
      id: "gecko",
      kind: "link",
      label: "Token on GeckoTerminal",
      hint: "pools · volume",
      href: `https://www.geckoterminal.com/${dex}/tokens/${address}`,
    });
  // Portfolio trackers index wallets across the chains they support; a vault contract
  // lives only on its own chain (Robinhood is not indexed there), so skip them for vaults.
  if (kind === "wallet" && plain) {
    out.push({
      id: "debank",
      kind: "link",
      label: "Portfolio on DeBank",
      hint: "holdings across chains",
      href: `https://debank.com/profile/${address}`,
    });
    out.push({
      id: "zerion",
      kind: "link",
      label: "Portfolio on Zerion",
      hint: "positions · history",
      href: `https://app.zerion.io/${address}/overview`,
    });
  }
  if (kind === "wallet" && plain)
    out.push({
      id: "krystal-positions",
      kind: "link",
      label: "LP positions on Krystal",
      hint: "this wallet's pools and vaults",
      href: withRef(`https://defi.krystal.app/account/${address}/positions`),
    });
  return out;
}
