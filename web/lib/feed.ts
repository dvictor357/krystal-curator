import { recordSample } from "@/lib/telemetry";

/** One dataset's shopping list from the backend: fetch these, post the results back. */
export interface Recipe {
  kind: "pools" | "positions" | "leaderboard" | "review";
  chain: number;
  round: number;
  wallet?: string;
  address?: string;
  steps: { name: string; url: string; params: Record<string, string> }[];
}

const CONCURRENCY = 6;

async function fetchStep(step: Recipe["steps"][number]) {
  const url = new URL(step.url);
  for (const [k, v] of Object.entries(step.params)) url.searchParams.set(k, v);
  try {
    const r = await fetch(url, { headers: { Accept: "application/json" } });
    if (!r.ok) return { __error: `HTTP ${r.status}` };
    return await r.json();
  } catch (e) {
    return { __error: e instanceof Error ? e.message : "network error" };
  }
}

async function runSteps(steps: Recipe["steps"]) {
  const payloads: Record<string, unknown> = {};
  let i = 0;
  await Promise.all(
    Array.from({ length: Math.min(CONCURRENCY, steps.length) }, async () => {
      while (i < steps.length) {
        const step = steps[i++];
        payloads[step.name] = await fetchStep(step);
      }
    }),
  );
  return payloads;
}

/**
 * Run one recipe to completion: fetch its steps from Krystal in this browser (the
 * user's IP is what Krystal accepts), post them to the backend, follow `next` rounds.
 */
export async function runRecipe(recipe: Recipe): Promise<void> {
  let current: Recipe | null = recipe;
  let rounds = 0;
  while (current && rounds++ < 4) {
    const started = performance.now();
    const payloads = await runSteps(current.steps);
    const upstreamMs = performance.now() - started;
    const failed = Object.values(payloads).filter(
      (p) => p && typeof p === "object" && "__error" in (p as object),
    ).length;
    recordSample({
      at: Date.now(),
      path: `krystal:${current.kind}`,
      ms: upstreamMs,
      ok: failed < current.steps.length,
      status: failed ? 206 : 200,
      cache: "miss",
      upstreamMs,
      error: failed
        ? `${failed}/${current.steps.length} requests failed`
        : undefined,
    });
    const r: Response = await fetch(`/api/market/feed/${current.kind}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chain: current.chain,
        round: current.round,
        wallet: current.wallet ?? "",
        address: current.address ?? "",
        upstreamMs: Math.round(upstreamMs),
        payloads,
      }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok)
      throw new Error(body.error || "Could not hand the data to the server.");
    current = body.next ?? null;
  }
}

const running = new Map<string, Promise<void>>();

/** Run recipes, sharing an in-flight run of the same dataset between callers. */
export async function runRecipes(recipes: Recipe[]) {
  await Promise.all(
    recipes.map((r) => {
      const id = `${r.kind}:${r.chain}:${r.wallet ?? ""}:${r.address ?? ""}`;
      let run = running.get(id);
      if (!run) {
        run = runRecipe(r).finally(() => running.delete(id));
        running.set(id, run);
      }
      return run;
    }),
  );
}
