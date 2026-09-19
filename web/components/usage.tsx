"use client";
import { useEffect, useState } from "react";
import { request } from "@/lib/api";

type Report = {
  days: number;
  totalUsers: number;
  activeUsers: number;
  activeUsers7d: number;
  requests: number;
  perDay: { day: string; requests: number; users: number }[];
  perRoute: {
    route: string;
    requests: number;
    errors: number;
    avgMs: number;
    users: number;
  }[];
  topUsers: { label: string; requests: number; activeDays: number }[];
};

/** Admin-only usage report: accounts, requests per day and per route, top accounts. */
export function UsagePanel() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Report | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    request(`/api/market/usage?days=${days}`)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [days]);
  if (error) return <p className="notice error">{error}</p>;
  if (!data) return <p className="fine-print">Loading usage…</p>;
  const peak = Math.max(1, ...data.perDay.map((d) => d.requests));
  return (
    <section className="usage-panel">
      <header className="usage-head">
        <span className="eyebrow">Usage · admin</span>
        <span className="usage-range">
          {[7, 30, 90].map((n) => (
            <button
              key={n}
              type="button"
              className={n === days ? "on" : ""}
              onClick={() => setDays(n)}
            >
              {n} d
            </button>
          ))}
        </span>
      </header>
      <div className="metric-grid track-grid">
        <div className="metric">
          <span>ACCOUNTS</span>
          <strong>{data.totalUsers}</strong>
          <small>
            {data.activeUsers} active in window · {data.activeUsers7d} last 7 d
          </small>
        </div>
        <div className="metric">
          <span>REQUESTS</span>
          <strong>{data.requests.toLocaleString("en-US")}</strong>
          <small>authenticated API calls</small>
        </div>
        <div className="metric">
          <span>PER ACTIVE USER</span>
          <strong>
            {data.activeUsers
              ? Math.round(data.requests / data.activeUsers)
              : 0}
          </strong>
          <small>requests in window</small>
        </div>
        <div className="metric">
          <span>TOP ROUTE</span>
          <strong>{data.perRoute[0]?.requests ?? 0}</strong>
          <small>{data.perRoute[0]?.route ?? "—"}</small>
        </div>
      </div>
      <div className="usage-bars" aria-label="Requests per day">
        {data.perDay.map((d) => (
          <div
            key={d.day}
            className="usage-bar"
            title={`${d.day}: ${d.requests} requests, ${d.users} users`}
          >
            <span
              style={{ height: `${Math.max(2, (d.requests / peak) * 100)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="usage-tables">
        <table>
          <thead>
            <tr>
              <th>ROUTE</th>
              <th>REQ</th>
              <th>ERR</th>
              <th>AVG MS</th>
              <th>USERS</th>
            </tr>
          </thead>
          <tbody>
            {data.perRoute.map((r) => (
              <tr key={r.route}>
                <td>{r.route}</td>
                <td>{r.requests}</td>
                <td className={r.errors ? "amber" : ""}>{r.errors}</td>
                <td>{Math.round(r.avgMs)}</td>
                <td>{r.users}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <table>
          <thead>
            <tr>
              <th>ACCOUNT</th>
              <th>REQ</th>
              <th>ACTIVE DAYS</th>
            </tr>
          </thead>
          <tbody>
            {data.topUsers.map((u) => (
              <tr key={u.label}>
                <td>{u.label}</td>
                <td>{u.requests}</td>
                <td>{u.activeDays}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
