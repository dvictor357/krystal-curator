import { useSyncExternalStore } from "react";

/** One bridge round-trip as the status bar sees it. */
export interface Sample {
  at: number;
  path: string;
  ms: number;
  ok: boolean;
  status: number;
  cache: "hit" | "stale" | "miss" | "";
  upstreamMs: number;
  error?: string;
}

export interface Telemetry {
  samples: Sample[];
  online: boolean;
  dataAt: number | null;
  interval: number | null;
}

let state: Telemetry = {
  samples: [],
  online: true,
  dataAt: null,
  interval: null,
};
const listeners = new Set<() => void>();
function emit(next: Partial<Telemetry>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}
export function recordSample(sample: Sample) {
  emit({ samples: [sample, ...state.samples].slice(0, 12) });
}
export function setDataAt(dataAt: number | null, interval: number | null) {
  if (state.dataAt !== dataAt || state.interval !== interval)
    emit({ dataAt, interval });
}
export function setOnline(online: boolean) {
  if (state.online !== online) emit({ online });
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
const server: Telemetry = state;
export function useTelemetry() {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => server,
  );
}
/** Which upstream the bridge path fans out to; shown next to the upstream latency. */
export function upstreamName(path: string) {
  if (path.includes("/market/pools")) return "Krystal";
  if (path.includes("/market/")) return "Krystal";
  return "Backend";
}
