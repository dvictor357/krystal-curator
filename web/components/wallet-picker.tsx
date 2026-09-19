"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Loader2, X } from "lucide-react";
import { useWallets, type WalletOption } from "@/lib/wallets";

/** Modal list of the wallets this browser exposes; `connect` runs the sign-in for one. */
export function WalletPicker({
  connect,
  close,
}: {
  connect: (wallet: WalletOption) => Promise<void>;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const { wallets, settled } = useWallets();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    const el = dialog.current;
    el?.showModal();
    return () => {
      el?.close();
    };
  }, []);
  async function pick(wallet: WalletOption) {
    setBusy(wallet.id);
    setMessage("");
    try {
      await connect(wallet);
    } catch (e) {
      setMessage(
        e instanceof Error ? e.message : "Wallet sign-in failed. Try again.",
      );
      setBusy(null);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="wallet-dialog"
      aria-labelledby="wallet-picker-title"
      onCancel={(e) => {
        if (busy) e.preventDefault();
        else close();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) close();
      }}
    >
      <div className="wallet-inner">
        <header className="detail-sticky-bar">
          <span className="eyebrow">Connect wallet</span>
          <button
            className="icon-button"
            onClick={close}
            disabled={Boolean(busy)}
            aria-label="Close wallet picker"
          >
            <X size={20} />
          </button>
        </header>
        <h2 id="wallet-picker-title">Choose a wallet.</h2>
        <p>
          You will sign one message to prove ownership. No transaction, gas, or
          token approval.
        </p>
        {wallets.length > 0 ? (
          <ul className="wallet-list">
            {wallets.map((w) => (
              <li key={w.id}>
                <button
                  className="wallet-option"
                  disabled={Boolean(busy)}
                  aria-busy={busy === w.id}
                  onClick={() => pick(w)}
                >
                  {w.icon ? (
                    <img src={w.icon} alt="" className="wallet-icon" />
                  ) : (
                    <span className="wallet-icon wallet-icon-fallback">
                      {w.name.slice(0, 1)}
                    </span>
                  )}
                  <span className="wallet-name">
                    {w.name}
                    <small>{w.rdns}</small>
                  </span>
                  {busy === w.id ? (
                    <Loader2 size={16} className="spin" />
                  ) : (
                    <ArrowRight size={16} />
                  )}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="wallet-empty">
            {settled
              ? "No browser wallet detected. Install one, then reload this page."
              : "Looking for wallets…"}
          </p>
        )}
        <p role="status" className="form-status">
          {busy && !message ? "Confirm in your wallet…" : message}
        </p>
      </div>
    </dialog>
  );
}
