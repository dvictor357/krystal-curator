"use client";
import { useState } from "react";
import {
  feeLabel,
  protocolLabel,
  safeLogo,
  splitPair,
  tokenGlyph,
  tokenTone,
} from "@/lib/pair";
import type { Pool } from "@/lib/types";

function TokenDisc({
  symbol,
  logo,
  size,
}: {
  symbol: string;
  logo?: string;
  size: "sm" | "md" | "lg";
}) {
  const [broken, setBroken] = useState(false);
  const src = broken ? "" : safeLogo(logo);
  return (
    <span
      className={`token-disc ${tokenTone(symbol)} disc-${size}`}
      title={symbol}
    >
      {src ? (
        <img
          src={src}
          alt=""
          width={size === "lg" ? 44 : size === "md" ? 30 : 24}
          height={size === "lg" ? 44 : size === "md" ? 30 : 24}
          onError={() => setBroken(true)}
          referrerPolicy="no-referrer"
        />
      ) : (
        <span>{tokenGlyph(symbol)}</span>
      )}
    </span>
  );
}

export function PairMark({
  pool,
  quote = "",
  size = "md",
  showMeta = true,
  source = false,
}: {
  pool: Pick<
    Pool,
    | "pair"
    | "token0"
    | "token1"
    | "token0Logo"
    | "token1Logo"
    | "protocol"
    | "feeTier"
  > & { source?: string };
  quote?: string;
  size?: "sm" | "md" | "lg";
  showMeta?: boolean;
  source?: boolean;
}) {
  const [token0, token1] = splitPair(pool);
  const fee = feeLabel(pool.feeTier);
  const quoteKey = quote.toUpperCase();
  return (
    <span className={`pair-mark pair-${size}`}>
      <span className="pair-stack" aria-hidden="true">
        <TokenDisc symbol={token0} logo={pool.token0Logo} size={size} />
        <TokenDisc symbol={token1} logo={pool.token1Logo} size={size} />
      </span>
      <span className="pair-copy">
        <span className="pair-names">
          <span
            className={
              quoteKey && token0.toUpperCase() === quoteKey ? "is-quote" : ""
            }
          >
            {token0}
          </span>
          <span className="pair-slash">/</span>
          <span
            className={
              quoteKey && token1.toUpperCase() === quoteKey ? "is-quote" : ""
            }
          >
            {token1}
          </span>
        </span>
        {showMeta && (
          <small className="pair-meta">
            <span>{protocolLabel(pool.protocol)}</span>
            {fee && <span className="fee-chip">{fee}</span>}
            {source && pool.source ? (
              <span className="muted">{pool.source}</span>
            ) : null}
          </small>
        )}
      </span>
    </span>
  );
}
