import { getAddress, toHex, type EIP1193Provider } from "viem";
import { createSiweMessage } from "viem/siwe";
import { request } from "@/lib/api";

/** EIP-4361 sign-in with the chosen wallet: nonce → personal_sign → session cookie. */
export async function signInWithWallet(
  provider: EIP1193Provider,
): Promise<string> {
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
  let signature: string;
  try {
    signature = (await provider.request({
      method: "personal_sign",
      params: [toHex(message), address],
    })) as string;
  } catch (e) {
    // EIP-1193 user rejection; other provider errors keep their own text.
    if ((e as { code?: number })?.code === 4001)
      throw new Error("Signature request was rejected in the wallet.");
    throw e;
  }
  await request("/api/auth/siwe", {
    method: "POST",
    body: JSON.stringify({ message, signature }),
  });
  return address;
}

export function shortAddress(address: string) {
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}
