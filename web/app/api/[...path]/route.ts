import { NextResponse } from "next/server";
const allowed = new Map([
  ["auth/login", ["POST"]],
  ["auth/register", ["POST"]],
  ["auth/logout", ["POST"]],
  ["auth/nonce", ["GET"]],
  ["auth/siwe", ["POST"]],
  ["account", ["GET", "POST"]],
  ["market/pools", ["GET"]],
  ["market/positions", ["GET"]],
  ["market/rotations", ["GET"]],
  ["market/track-record", ["GET"]],
  ["market/usage", ["GET"]],
  ["market/feed/pools", ["POST"]],
  ["market/feed/positions", ["POST"]],
  ["market/feed/leaderboard", ["POST"]],
  ["market/feed/review", ["POST"]],
  ["market/leaderboard", ["GET"]],
  ["market/review", ["GET"]],
]);
async function bridge(
  req: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const path = (await params).path.join("/");
  if (!allowed.get(path)?.includes(req.method))
    return NextResponse.json({ error: "Not found." }, { status: 404 });
  const expectedOrigin = process.env.CURATOR_ORIGIN || new URL(req.url).origin;
  if (req.method !== "GET" && req.headers.get("origin") !== expectedOrigin)
    return NextResponse.json(
      { error: "Invalid request origin." },
      { status: 403 },
    );
  const secret = process.env.CURATOR_API_SECRET;
  if (!secret || secret.length < 32)
    return NextResponse.json(
      {
        error:
          "Account and analytics services are not configured on this deployment.",
      },
      { status: 503 },
    );
  try {
    const body = req.method === "GET" ? undefined : await req.text();
    // Browser-fed Krystal payloads are large; everything else stays tiny.
    const limit = path.startsWith("market/feed/") ? 8 * 1024 * 1024 : 4096;
    if (body && body.length > limit)
      return NextResponse.json(
        { error: "Request too large." },
        { status: 413 },
      );
    const target = new URL(
      `/${path.replace(/^market\//, "")}`,
      process.env.CURATOR_API_URL || "http://127.0.0.1:8100",
    );
    target.search = new URL(req.url).search;
    // Only trust client-IP metadata when a configured reverse proxy overwrites this header.
    const peer =
      process.env.CURATOR_TRUST_PROXY === "true"
        ? req.headers.get("x-real-ip") || "unknown"
        : "local";
    const response = await fetch(target, {
      method: req.method,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(90000),
      headers: {
        Authorization: `Bearer ${secret}`,
        "Content-Type": "application/json",
        Cookie: req.headers.get("cookie") || "",
        "X-Curator-Client": peer,
        // SIWE messages must be bound to this deployment, not to whatever the client claims.
        "X-Curator-Origin": expectedOrigin,
      },
    });
    const payload = await response.json();
    const message =
      typeof payload.detail === "string"
        ? payload.detail
        : response.status === 422
          ? "Check the email, password, or settings you entered."
          : "Request failed.";
    const result = NextResponse.json(
      response.ok ? payload : { error: message },
      {
        status: response.status,
        headers: { "Cache-Control": "private, no-store" },
      },
    );
    for (const cookie of response.headers.getSetCookie())
      result.headers.append("Set-Cookie", cookie);
    for (const name of [
      "retry-after",
      "x-cache",
      "x-upstream-ms",
      "x-data-age",
    ])
      if (response.headers.has(name))
        result.headers.set(name, response.headers.get(name)!);
    return result;
  } catch {
    return NextResponse.json(
      { error: "Service unavailable. Please try again shortly." },
      { status: 503 },
    );
  }
}
export { bridge as GET, bridge as POST };
