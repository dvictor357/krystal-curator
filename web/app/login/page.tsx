"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, ArrowLeft, KeyRound, Wallet } from "lucide-react";
import { Brand } from "@/components/brand";
import { WalletPicker } from "@/components/wallet-picker";
import { request } from "@/lib/api";
import { signInWithWallet } from "@/lib/siwe";
import { hasSession } from "@/lib/session";
import type { WalletOption } from "@/lib/wallets";
export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [picker, setPicker] = useState(false);
  // Already signed in: skip the form.
  useEffect(() => {
    hasSession().then((ok) => {
      if (ok) window.location.replace("/app");
    });
  }, []);
  async function connect(wallet: WalletOption) {
    await signInWithWallet(wallet.provider);
    window.location.assign("/app");
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await request(`/api/auth/${register ? "register" : "login"}`, {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      window.location.assign("/app");
    } catch (e) {
      setMessage(
        e instanceof Error ? e.message : "Sign-in failed. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <header className="site-header">
        <Brand />
        <Link href="/" className="text-link">
          <ArrowLeft size={16} /> Back to home
        </Link>
      </header>
      <main id="main" className="login-card">
        <KeyRound className="amber" size={32} />
        <div className="eyebrow">Your LP workspace</div>
        <h1>{register ? "Create a workspace." : "Welcome back."}</h1>
        <p>
          Save pairs, set a risk profile, and screen live pools. Sign in with
          your wallet, or with an email and password.
        </p>
        <button
          type="button"
          className="button wallet-button"
          disabled={busy}
          onClick={() => setPicker(true)}
        >
          <Wallet size={17} />
          Sign in with wallet
        </button>
        {picker && (
          <WalletPicker connect={connect} close={() => setPicker(false)} />
        )}
        <small className="wallet-note">
          Signature only. No transaction, gas, or token approval is requested.
        </small>
        <div className="login-divider">or</div>
        <form onSubmit={submit}>
          <label>
            Email address
            <input
              required
              type="email"
              autoComplete="email"
              maxLength={254}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              required
              type="password"
              autoComplete={register ? "new-password" : "current-password"}
              aria-describedby={register ? "password-help" : undefined}
              minLength={12}
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {register && (
            <small id="password-help">
              Use at least 12 characters. A unique passphrase works well.
            </small>
          )}
          <button className="button secondary" disabled={busy}>
            {busy
              ? "Please wait…"
              : register
                ? "Create account"
                : "Enter workspace"}{" "}
            <ArrowRight size={17} />
          </button>
          <button
            type="button"
            className="text-link"
            onClick={() => {
              setRegister(!register);
              setMessage("");
            }}
          >
            {register
              ? "Already have an account? Sign in"
              : "New here? Create an account"}
          </button>
        </form>
        <p role="status" className="form-status">
          {message}
        </p>
        <Link href="/demo" className="text-link">
          Try the sample book first <ArrowRight size={15} />
        </Link>
        <small>
          Email accounts need no wallet; wallet accounts never send a
          transaction.
        </small>
      </main>
    </div>
  );
}
