import { useCallback, useEffect, useRef, useState } from "react";
import { recordSample, setDataAt, setOnline } from "@/lib/telemetry";
import { runRecipes, type Recipe } from "@/lib/feed";

interface Entry<T> {
  data: T;
  at: number;
  fetchedAt: number | null;
}
interface Options {
  /** Seconds a cached copy is shown without revalidating. */
  ttl: number;
  /** Seconds between background refreshes while the tab is visible; 0 disables. */
  interval?: number;
  enabled?: boolean;
}
export interface Resource<T> {
  data: T | null;
  fetchedAt: number | null;
  busy: boolean;
  revalidating: boolean;
  error: string;
  refresh: () => void;
}

const memory = new Map<string, Entry<unknown>>();
const inflight = new Map<string, Promise<Entry<unknown>>>();
const PREFIX = "curator:";

function read<T>(key: string): Entry<T> | null {
  const hit = memory.get(key);
  if (hit) return hit as Entry<T>;
  try {
    const raw = sessionStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const entry = JSON.parse(raw) as Entry<T>;
    memory.set(key, entry);
    return entry;
  } catch {
    return null;
  }
}
function write<T>(key: string, entry: Entry<T>) {
  memory.set(key, entry);
  try {
    sessionStorage.setItem(PREFIX + key, JSON.stringify(entry));
  } catch {
    // Quota or private mode: memory copy still serves this visit.
  }
}
export function clearResources() {
  memory.clear();
  try {
    Object.keys(sessionStorage)
      .filter((k) => k.startsWith(PREFIX))
      .forEach((k) => sessionStorage.removeItem(k));
  } catch {
    // ignore
  }
}

const refreshing = new Set<string>();
const listeners = new Map<string, Set<(e: Entry<unknown>) => void>>();

/** Bridge GET with timing and cache headers recorded for the status bar. */
async function load<T>(
  path: string,
  fresh: boolean,
  fed = false,
): Promise<Entry<T>> {
  const url = fresh
    ? `${path}${path.includes("?") ? "&" : "?"}fresh=true`
    : path;
  const started = performance.now();
  let response: Response;
  try {
    response = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    });
  } catch (e) {
    recordSample({
      at: Date.now(),
      path,
      ms: performance.now() - started,
      ok: false,
      status: 0,
      cache: "",
      upstreamMs: 0,
      error: "Network error",
    });
    setOnline(navigator.onLine);
    throw e instanceof Error ? e : new Error("Network error");
  }
  const body = await response.json().catch(() => ({}));
  recordSample({
    at: Date.now(),
    path,
    ms: performance.now() - started,
    ok: response.ok,
    status: response.status,
    cache: (response.headers.get("x-cache") as "hit" | "stale" | "miss") || "",
    upstreamMs: Number(response.headers.get("x-upstream-ms") || 0),
    error: response.ok ? undefined : body.error,
  });
  setOnline(true);
  if (response.ok && Array.isArray(body.needFeed) && !fed) {
    // Browser-fed deployment: fetch what the server asks for, post it, ask again.
    await runRecipes(body.needFeed as Recipe[]);
    return load<T>(path, false, true);
  }
  if (!response.ok) {
    if (response.status === 401) window.location.assign("/login");
    throw new Error(body.error || "Request failed. Please try again.");
  }
  const entry: Entry<T> = {
    data: body as T,
    at: Date.now(),
    fetchedAt: body.fetchedAt ?? null,
  };
  const stale = (body as { refreshFeed?: Recipe[] }).refreshFeed;
  if (stale && !fed && !refreshing.has(path)) {
    // Stale answer served at once; refresh the feed in the background, then swap.
    refreshing.add(path);
    runRecipes(stale)
      .then(() => load<T>(path, false, true))
      .then((next) => {
        write(path, next);
        listeners.get(path)?.forEach((l) => l(next));
      })
      .catch(() => undefined)
      .finally(() => refreshing.delete(path));
  }
  return entry;
}

function fetchShared<T>(key: string, path: string, fresh: boolean) {
  const running = inflight.get(key);
  if (running && !fresh) return running as Promise<Entry<T>>;
  const promise = load<T>(path, fresh)
    .then((entry) => {
      write(key, entry);
      return entry;
    })
    .finally(() => {
      if (inflight.get(key) === promise) inflight.delete(key);
    });
  inflight.set(key, promise);
  return promise;
}

/** One-off bridge GET that honours the browser-fed handshake (no caching, no hook). */
export async function fetchFed<T>(path: string): Promise<T> {
  return (await load<T>(path, false)).data;
}

/**
 * Cached bridge resource: last copy shows at once (memory → sessionStorage), revalidates
 * when older than `ttl`, refreshes every `interval` while visible, one request per key
 * however many components ask. `path` null = nothing to load.
 */
export function useResource<T extends { fetchedAt?: number | null }>(
  path: string | null,
  { ttl, interval = 0, enabled = true }: Options,
): Resource<T> {
  const key = enabled && path ? path : null;
  const [entry, setEntry] = useState<Entry<T> | null>(() =>
    key && typeof window !== "undefined" ? read<T>(key) : null,
  );
  const [busy, setBusy] = useState(false);
  const [revalidating, setRevalidating] = useState(false);
  const [error, setError] = useState("");
  const current = useRef(key);
  current.current = key;

  const run = useCallback(
    (fresh: boolean) => {
      if (!key) return;
      const cached = read<T>(key);
      if (cached) setRevalidating(true);
      else setBusy(true);
      setError("");
      fetchShared<T>(key, key, fresh)
        .then((next) => {
          if (current.current === key) setEntry(next);
        })
        .catch((e) => {
          if (current.current === key)
            setError(e instanceof Error ? e.message : "Request failed.");
        })
        .finally(() => {
          if (current.current === key) {
            setBusy(false);
            setRevalidating(false);
          }
        });
    },
    [key],
  );

  useEffect(() => {
    if (!key) {
      setEntry(null);
      setError("");
      setBusy(false);
      return;
    }
    const cached = read<T>(key);
    setEntry(cached);
    setError("");
    if (!cached || Date.now() - cached.at > ttl * 1000) run(false);
    if (!interval) return;
    const tick = () => {
      if (document.visibilityState !== "visible") return;
      const latest = read<T>(key);
      if (!latest || Date.now() - latest.at > ttl * 1000) run(false);
    };
    const timer = window.setInterval(tick, interval * 1000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [key, ttl, interval, run]);

  useEffect(() => {
    if (key) setDataAt(entry?.fetchedAt ?? null, interval || null);
  }, [key, entry, interval]);
  // A background feed refresh replaced the stale copy: show it.
  useEffect(() => {
    if (!key) return;
    const set = listeners.get(key) ?? new Set();
    const l = (e: Entry<unknown>) => setEntry(e as Entry<T>);
    set.add(l);
    listeners.set(key, set);
    return () => {
      set.delete(l);
    };
  }, [key]);

  return {
    data: entry?.data ?? null,
    fetchedAt: entry?.fetchedAt ?? null,
    busy,
    revalidating,
    error,
    refresh: () => run(true),
  };
}
