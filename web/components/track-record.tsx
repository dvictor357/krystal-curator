"use client";
import { useEffect, useState } from "react";
import { money } from "@/lib/types";

type Record = {
  windowDays: number;
  generatedAt: number;
  verdicts: {
    total: number;
    rotate: number;
    consider: number;
    stay: number;
    none: number;
  };
  users: number;
  positions: number;
  judged: number;
  stay: {
    n: number;
    medianPredictedNetDay: number | null;
    medianRealisedFeeDay: number | null;
    medianRealisedOverPredicted: number | null;
  };
  rotate: {
    n: number;
    hitRate: number | null;
    medianPredictedUpliftDay: number | null;
    medianRealisedUpliftDay: number | null;
    medianDays: number | null;
  };
  poolSamples: number;
};

const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const signed = (v: number | null) =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${money(v)}/d`;

/**
 * Aggregate, anonymous scorecard of every verdict Curator gave in the window, judged
 * against what the positions and the alternative pools actually paid afterwards.
 */
export function TrackRecord({ compact = false }: { compact?: boolean }) {
  const [data, setData] = useState<Record | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    fetch("/api/market/track-record", { credentials: "same-origin" })
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.error || "Unavailable");
        if (!cancelled) setData(body);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, []);
  if (error)
    return compact ? null : (
      <p className="fine-print">Track record unavailable: {error}</p>
    );
  if (!data) return <p className="fine-print">Loading track record…</p>;
  const thin = data.judged < 10;
  return (
    <div className={`track-record${compact ? " compact" : ""}`}>
      <div className="metric-grid track-grid">
        <div className="metric">
          <span>VERDICTS · {data.windowDays} D</span>
          <strong>{data.verdicts.total}</strong>
          <small>
            {data.verdicts.rotate} rotate · {data.verdicts.consider} consider ·{" "}
            {data.verdicts.stay} stay · {data.positions} positions
          </small>
        </div>
        <div className="metric">
          <span>ROTATE HIT RATE</span>
          <strong
            className={
              data.rotate.hitRate == null
                ? ""
                : data.rotate.hitRate >= 0.5
                  ? "positive"
                  : "amber"
            }
          >
            {pct(data.rotate.hitRate)}
          </strong>
          <small>
            {data.rotate.n} judged · alternative out-earned staying after the
            switch cost
          </small>
        </div>
        <div className="metric">
          <span>UPLIFT · SAID VS PAID</span>
          <strong>{signed(data.rotate.medianRealisedUpliftDay)}</strong>
          <small>
            we said {signed(data.rotate.medianPredictedUpliftDay)} · median
          </small>
        </div>
        <div className="metric">
          <span>STAY CALIBRATION</span>
          <strong>
            {data.stay.medianRealisedOverPredicted == null
              ? "—"
              : `${data.stay.medianRealisedOverPredicted.toFixed(2)}×`}
          </strong>
          <small>
            realised fees ÷ predicted net · {data.stay.n} positions · 1.0× = on
            the money
          </small>
        </div>
      </div>
      <p className="fine-print">
        {thin
          ? `Collecting: ${data.judged} verdicts old enough to judge. A verdict is judged once a day has passed and the alternative pool was sampled at least twice.`
          : `${data.judged} verdicts judged across ${data.users} accounts, ${data.poolSamples} hourly pool samples. Anonymous, aggregate, no wallet leaves the server.`}{" "}
        Fees only, IL not netted; the switch cost is amortised over the days
        observed.
      </p>
    </div>
  );
}
