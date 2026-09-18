"use client";
import { useEffect, useState } from "react";
import { Activity, ChevronUp } from "lucide-react";
import {
  setOnline,
  upstreamName,
  useTelemetry,
  type Sample,
} from "@/lib/telemetry";

function tone(ms: number, ok: boolean) {
  if (!ok) return "bad";
  if (ms < 500) return "good";
  if (ms < 2000) return "warn";
  return "bad";
}
function fmtMs(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}
function ago(seconds: number) {
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  return `${Math.round(seconds / 3600)} h ago`;
}

/** Sticky strip under the workspace: last bridge latency, last upstream latency, data age. */
export function StatusBar({ demo = false }: { demo?: boolean }) {
  const t = useTelemetry();
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 5000);
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    setOnline(navigator.onLine);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  const last = t.samples[0];
  const upstream = t.samples.find((s) => s.upstreamMs > 0);
  const backendTone = !t.online
    ? "bad"
    : last
      ? tone(last.ms, last.ok)
      : "idle";
  const age = t.dataAt ? now / 1000 - t.dataAt : null;
  const stale = age != null && t.interval != null && age > t.interval * 2;
  return (
    <div className={`statusbar${open ? " open" : ""}`}>
      <button
        className="statusbar-summary"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label="Connection details"
      >
        <span className={`sb-dot ${backendTone}`} />
        {demo ? (
          <span>Demo · fixture snapshot · no network</span>
        ) : (
          <>
            <span>
              Backend <b>{!t.online ? "offline" : last ? fmtMs(own) : "—"}</b>
            </span>
            <span>
              {upstream ? upstreamName(upstream.path) : "Upstream"}{" "}
              <b>{upstream ? fmtMs(upstream.upstreamMs) : "cached"}</b>
            </span>
            <span className={stale ? "warn" : ""}>
              Data <b>{age != null ? ago(age) : "—"}</b>
            </span>
            {t.interval && (
              <span className="sb-muted">auto-refresh {t.interval} s</span>
            )}
            {last && !last.ok && last.error && (
              <span className="bad">{last.error}</span>
            )}
          </>
        )}
        <span className="sb-spacer" />
        <Activity size={11} />
        <ChevronUp size={11} className="sb-chevron" />
      </button>
      {open && !demo && (
        <ul className="statusbar-log">
          {t.samples.length === 0 && (
            <li className="sb-muted">No requests yet.</li>
          )}
          {t.samples.map((s: Sample, i) => (
            <li key={`${s.at}-${i}`}>
              <span
                className={`sb-dot ${tone(Math.max(0, s.ms - s.upstreamMs), s.ok)}`}
              />
              <span className="sb-time">
                {new Date(s.at).toLocaleTimeString()}
              </span>
              <span className="sb-path">
                {s.path.replace("/api/market/", "").split("?")[0]}
              </span>
              <span>{s.ok ? s.status : s.error || s.status || "error"}</span>
              <span>{fmtMs(s.ms)}</span>
              <span className="sb-muted">
                {s.cache ? `cache ${s.cache}` : ""}
                {s.upstreamMs > 0
                  ? ` · ${upstreamName(s.path)} ${fmtMs(s.upstreamMs)}`
                  : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
