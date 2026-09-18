import { getAddress, toHex, type EIP1193Provider } from "viem";
import { createSiweMessage } from "viem/siwe";
import { request } from "@/lib/api";

declare global {
  interface Window {
    ethereum?: EIP1193Provider;
  }
}

export function walletAvailable() {
  return typeof window !== "undefined" && Boolean(window.ethereum);
}

/** EIP-4361 sign-in with the injected wallet: nonce → personal_sign → session cookie. */
export async function signInWithWallet(): Promise<string> {
  const provider = window.ethereum;
  if (!provider)
    throw new Error("No wallet found. Install a browser wallet and try again.");
  const [account] = (await provider.request({
    method: "eth_requestAccounts",
  })) as string[];
  if (!account) throw new Error("The wallet did not share an account.");
  const address = getAddress(account);
  const chainId = Number(await provider.request({ method: "eth_chainId" }));
  const { nonce } = (await request("/api/auth/nonce")) as { nonce: string };
  const message = createSiweMessage({
    address,
    chainId,
    domain: window.location.host,
    nonce,
    uri: `${window.location.origin}/login`,
    version: "1",
    statement:
      "Sign in to Krystal Curator. This is a signature only: no transaction, no gas, no approvals.",
    issuedAt: new Date(),
    expirationTime: new Date(Date.now() + 5 * 60 * 1000),
  });
  const signature = (await provider.request({
    method: "personal_sign",
    params: [toHex(message), address],
  })) as string;
  await request("/api/auth/siwe", {
    method: "POST",
    body: JSON.stringify({ message, signature }),
  });
  return address;
}

export function shortAddress(address: string) {
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}
