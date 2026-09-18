import { useEffect, useState } from "react";
import type { EIP1193Provider } from "viem";

export interface WalletOption {
  id: string;
  name: string;
  rdns: string;
  icon?: string;
  provider: EIP1193Provider;
}

interface Announcement {
  info: { uuid: string; name: string; icon: string; rdns: string };
  provider: EIP1193Provider;
}

declare global {
  interface Window {
    ethereum?: EIP1193Provider;
  }
  interface WindowEventMap {
    "eip6963:announceProvider": CustomEvent<Announcement>;
  }
}

/** Only inline SVG/PNG data URIs render as wallet icons; anything else is dropped. */
function safeIcon(icon: string | undefined) {
  return icon && /^data:image\/(svg\+xml|png|webp|jpeg)[;,]/.test(icon)
    ? icon
    : undefined;
}

/**
 * Wallets present in this browser: EIP-6963 announcements first, with the
 * legacy `window.ethereum` as a single fallback entry when nothing announces.
 */
export function useWallets() {
  const [announced, setAnnounced] = useState<WalletOption[]>([]);
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const onAnnounce = (event: CustomEvent<Announcement>) => {
      const { info, provider } = event.detail ?? {};
      if (!info?.uuid || !provider || typeof provider.request !== "function")
        return;
      setAnnounced((list) =>
        list.some((w) => w.id === info.uuid || w.rdns === info.rdns)
          ? list
          : [
              ...list,
              {
                id: info.uuid,
                name: String(info.name || info.rdns || "Wallet").slice(0, 40),
                rdns: String(info.rdns || ""),
                icon: safeIcon(info.icon),
                provider,
              },
            ],
      );
    };
    window.addEventListener("eip6963:announceProvider", onAnnounce);
    window.dispatchEvent(new Event("eip6963:requestProvider"));
    const timer = window.setTimeout(() => setSettled(true), 400);
    return () => {
      window.removeEventListener("eip6963:announceProvider", onAnnounce);
      window.clearTimeout(timer);
    };
  }, []);
  const wallets =
    announced.length === 0 && settled && window.ethereum
      ? [
          {
            id: "injected",
            name: "Browser wallet",
            rdns: "window.ethereum",
            provider: window.ethereum,
          } satisfies WalletOption,
        ]
      : announced;
  return { wallets, settled };
}
