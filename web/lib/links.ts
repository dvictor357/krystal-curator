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
};

export type Action = {
  id: string;
  label: string;
  hint?: string;
  href?: string;
  copy?: string;
  kind: "copy" | "link";
};

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
      href: extra.krystalUrl,
    });
  if (kind === "vault" && extra.krystalUrl)
    out.push({
      id: "krystal",
      kind: "link",
      label: "Open vault on Krystal",
      hint: "deposit · strategy · history",
      href: extra.krystalUrl,
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
  if ((kind === "wallet" || kind === "vault") && plain) {
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
      href: `https://defi.krystal.app/account/${address}/positions`,
    });
  return out;
}
