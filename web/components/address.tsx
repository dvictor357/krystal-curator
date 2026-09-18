"use client";
import { MoreHorizontal } from "lucide-react";
import { usePalette } from "@/components/palette";
import { addressActions, shorten } from "@/lib/links";

/** An address you can act on: click for copy / explorer / portfolio links. */
export function AddressChip({
  address,
  chain,
  kind,
  label,
  full = false,
  krystalUrl,
  className = "",
}: {
  address: string;
  chain: number;
  kind: "wallet" | "pool" | "token" | "vault";
  label?: string;
  full?: boolean;
  krystalUrl?: string;
  className?: string;
}) {
  const open = usePalette();
  if (!address) return null;
  return (
    <button
      type="button"
      className={`address-chip ${className}`}
      title="Copy, explorer, portfolio…"
      onClick={(e) => {
        e.stopPropagation();
        open({
          title: label ?? `${kind} address`,
          subtitle: address,
          actions: addressActions(kind, address, chain, { krystalUrl }),
        });
      }}
    >
      <code>{full ? address : shorten(address)}</code>
      <MoreHorizontal size={12} />
    </button>
  );
}

/** Token symbol that opens the token's actions; falls back to plain text without an address. */
export function TokenLink({
  symbol,
  address,
  chain,
  className = "",
}: {
  symbol: string;
  address?: string;
  chain: number;
  className?: string;
}) {
  const open = usePalette();
  if (!address) return <span className={className}>{symbol}</span>;
  return (
    <button
      type="button"
      className={`token-link ${className}`}
      title={`${symbol}: copy, explorer, chart…`}
      onClick={(e) => {
        e.stopPropagation();
        open({
          title: `${symbol} · token`,
          subtitle: address,
          actions: addressActions("token", address, chain, { symbol }),
        });
      }}
    >
      {symbol}
    </button>
  );
}
