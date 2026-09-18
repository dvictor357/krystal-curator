"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowDownUp,
  ArrowUpRight,
  Bookmark,
  Check,
  ChevronRight,
  CircleHelp,
  Crosshair,
  Layers3,
  LayoutGrid,
  LogOut,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import { Brand } from "./brand";
import { PairMark } from "./pair";
import { request } from "@/lib/api";
import { protocolLabel } from "@/lib/pair";
import { chains, profiles } from "@/lib/validation";
import { defaults, money, pct, type Pool, type Settings } from "@/lib/types";
import snapshot from "@/lib/demo.json";
const tabs = [
  { id: "screener", label: "Pool screener", icon: LayoutGrid },
  { id: "watchlist", label: "Watchlist", icon: Bookmark },
  { id: "positions", label: "My positions", icon: Wallet },
  { id: "leaderboard", label: "Vault leaderboard", icon: Layers3 },
  { id: "settings", label: "Settings", icon: Settings2 },
];
export function Workspace({
  demo = false,
  page = "screener",
}: {
  demo?: boolean;
  page?: string;
}) {
  const [active, setActive] = useState(page);
  const [ready, setReady] = useState(demo);
  const [email, setEmail] = useState("");
  const [settings, setSettings] = useState<Settings>(defaults);
  const [watched, setWatched] = useState<string[]>([]);
  const [rows, setRows] = useState<Pool[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [protocol, setProtocol] = useState("all");
  const [quote, setQuote] = useState("USDG");
  const [sort, setSort] = useState("score");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [timestamp, setTimestamp] = useState<number | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [mutating, setMutating] = useState(false);
  const sequence = useRef(0);
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    setActive(page);
  }, [page]);
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "/") return;
      const target = event.target;
      if (
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        (target instanceof HTMLElement && target.isContentEditable)
      )
        return;
      event.preventDefault();
      searchRef.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (demo) return;
    let cancelled = false;
    request("/api/account")
      .then((account) => {
        if (!cancelled) {
          setEmail(account.email);
          setSettings(account.settings || defaults);
          setWatched(account.watchlist);
          setReady(true);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [demo]);
  useEffect(() => {
    if (!ready || !["screener", "watchlist"].includes(active)) return;
    const id = ++sequence.current;
    setBusy(true);
    setError("");
    setRows([]);
    setSelected(null);
    setTimestamp(null);
    if (demo) {
      const data = snapshot[
        settings.profile as keyof typeof snapshot
      ] as Pool[];
      setRows(data);
      setBusy(false);
      return;
    }
    const params = new URLSearchParams({
      chain: String(settings.chain),
      source: settings.source,
      profile: settings.profile,
      size: String(settings.size),
      quote,
    });
    request(`/api/market/pools?${params}`)
      .then((data) => {
        if (id === sequence.current) {
          setRows(data.rows);
          setTimestamp(data.fetchedAt);
        }
      })
      .catch((e) => {
        if (id === sequence.current) setError(e.message);
      })
      .finally(() => {
        if (id === sequence.current) setBusy(false);
      });
    return () => {
      sequence.current++;
    };
  }, [
    ready,
    active,
    settings.chain,
    settings.source,
    settings.profile,
    settings.size,
    quote,
    refresh,
    demo,
  ]);
  async function toggleWatch(pool: Pool) {
    if (mutating) return;
    setMutating(true);
    setNotice("");
    const value = !watched.includes(pool.id);
    try {
      if (!demo)
        await request("/api/account", {
          method: "POST",
          body: JSON.stringify({
            action: "watch",
            poolId: pool.id,
            watched: value,
          }),
        });
      setWatched((prev) =>
        value ? [...prev, pool.id] : prev.filter((x) => x !== pool.id),
      );
      setNotice(
        demo
          ? "Demo watchlist updated for this visit only."
          : value
            ? "Pool saved to your watchlist."
            : "Pool removed from your watchlist.",
      );
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Could not update watchlist.");
    } finally {
      setMutating(false);
    }
  }
  const visible = rows
    .filter(
      (p) =>
        (active !== "watchlist" || watched.includes(p.id)) &&
        (protocol === "all" || p.protocol === protocol) &&
        `${p.pair} ${p.token0 ?? ""} ${p.token1 ?? ""} ${p.address}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .sort(
      (a, b) => Number(b[sort as keyof Pool]) - Number(a[sort as keyof Pool]),
    );
  const pool = rows.find((p) => p.id === selected);
  const title = tabs.find((t) => t.id === active)?.label || "Pool screener";
  const total = visible.reduce((n, p) => n + p.tvl, 0);
  function navigate(id: string) {
    setActive(id);
    setSelected(null);
    setNotice("");
  }
  return (
    <div className="workspace">
      <aside className="sidebar">
        <Brand />
        <div className="workspace-label">
          Workspace <span>live</span>
        </div>
        <nav aria-label="Workspace navigation">
          {tabs.map((t) =>
            demo ? (
              <button
                key={t.id}
                className={active === t.id ? "nav-item active" : "nav-item"}
                onClick={() => navigate(t.id)}
              >
                <t.icon size={17} />
                {t.label}
                {t.id === "watchlist" && (
                  <span className="count">{watched.length}</span>
                )}
              </button>
            ) : (
              <Link
                key={t.id}
                href={t.id === "screener" ? "/app" : `/app/${t.id}`}
                className={active === t.id ? "nav-item active" : "nav-item"}
              >
                <t.icon size={17} />
                {t.label}
                {t.id === "watchlist" && (
                  <span className="count">{watched.length}</span>
                )}
              </Link>
            ),
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <Crosshair size={20} />
            <p>
              Rank the pair.
              <br />
              <span>You size the range.</span>
            </p>
          </div>
          <Link href="/#method" className="nav-item">
            <CircleHelp size={17} /> How it works <ArrowUpRight size={13} />
          </Link>
          {demo ? (
            <Link className="account-card" href="/login">
              <span className="avatar">C</span>
              <span>
                Create a workspace
                <small>Sign in to keep a watchlist</small>
              </span>
              <ChevronRight size={16} />
            </Link>
          ) : (
            <button
              className="account-card"
              onClick={() =>
                request("/api/auth/logout", { method: "POST" })
                  .then(() => window.location.assign("/login"))
                  .catch((e) => setNotice(e.message))
              }
            >
              <span className="avatar">{email.slice(0, 1).toUpperCase()}</span>
              <span className="account-email">
                {email}
                <small>Sign out</small>
              </span>
              <LogOut size={15} />
            </button>
          )}
        </div>
      </aside>
      <div className="workspace-main">
        <header className="app-topbar">
          <span>
            Workspace <ChevronRight size={12} /> <b>{title}</b>
          </span>
          <span className="connection">
            <span className="status-dot" />
            {demo ? "Demo · sample snapshot" : "Read-only analytics"}
          </span>
        </header>
        {!demo && ready && (
          <button
            className="mobile-signout text-link"
            onClick={() =>
              request("/api/auth/logout", { method: "POST" })
                .then(() => window.location.assign("/login"))
                .catch((e) => setNotice(e.message))
            }
          >
            <LogOut size={14} /> Sign out
          </button>
        )}
        <main id="main" className="app-content">
          {demo && (
            <div className="demo-banner">
              <span>
                <strong>Sample book.</strong> Fixture data, not a live market.
                Watchlist changes last for this visit.
              </span>
              <Link href="/login">
                Create an account <ArrowUpRight size={14} />
              </Link>
            </div>
          )}
          <div className="app-heading">
            <div className="eyebrow">
              {active === "screener"
                ? "Screen · inspect · shortlist"
                : "Your liquidity workspace"}
              <h1>
                {title}
                <span className="amber">.</span>
              </h1>
              <p>
                {active === "screener"
                  ? "Ranked pairs matching this profile and quote."
                  : active === "watchlist"
                    ? "Pairs you marked for a second look."
                    : "Context for the next size decision."}
              </p>
            </div>
            {active !== "settings" && (
              <button
                className="button secondary small"
                disabled={busy || !ready}
                onClick={() => {
                  setRefresh((n) => n + 1);
                  setNotice(demo ? "Sample snapshot reloaded." : "");
                }}
              >
                <RefreshCw size={15} className={busy ? "spinning" : ""} />
                Refresh
              </button>
            )}
          </div>
          {!ready ? (
            <div className="empty" role="status">
              {error || "Opening your workspace…"}
              {error && (
                <button
                  className="button secondary"
                  onClick={() => window.location.reload()}
                >
                  Try again
                </button>
              )}
            </div>
          ) : (
            <>
              {["screener", "watchlist"].includes(active) && (
                <>
                  <div className="metric-grid">
                    <Metric
                      label="Pairs in view"
                      value={String(visible.length).padStart(2, "0")}
                      note={
                        active === "watchlist"
                          ? "Saved pools matching filters"
                          : "Matching this risk profile"
                      }
                    />
                    <Metric
                      label="Total value locked"
                      value={money(total, true)}
                      note="Across the current selection"
                    />
                    <Metric
                      label="24h trading fees"
                      value={money(
                        visible.reduce((n, p) => n + p.fees, 0),
                        true,
                      )}
                      note="Reported by the selected source"
                    />
                    <Metric
                      label="Risk profile"
                      value={settings.profile}
                      note="Filters and weighted scoring"
                      accent
                    />
                  </div>
                  <div className="filters">
                    <label>
                      <span>Network</span>
                      <select
                        aria-label="Network"
                        disabled={demo}
                        value={settings.chain}
                        onChange={(e) =>
                          setSettings({
                            ...settings,
                            chain: Number(e.target.value),
                            source: "krystal",
                          })
                        }
                      >
                        {Object.entries(chains).map(([k, v]) => (
                          <option key={k} value={k}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>Source</span>
                      <select
                        aria-label="Source"
                        disabled={demo}
                        value={settings.source}
                        onChange={(e) =>
                          setSettings({ ...settings, source: e.target.value })
                        }
                      >
                        <option value="krystal">Krystal</option>
                        {settings.chain === 4663 && (
                          <option value="rhpools">rhpools</option>
                        )}
                      </select>
                    </label>
                    <label>
                      <span>Risk profile</span>
                      <select
                        aria-label="Risk profile"
                        value={settings.profile}
                        onChange={(e) =>
                          setSettings({ ...settings, profile: e.target.value })
                        }
                      >
                        {profiles.map((p) => (
                          <option key={p}>{p}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>Protocol</span>
                      <select
                        aria-label="Protocol"
                        value={protocol}
                        onChange={(e) => setProtocol(e.target.value)}
                      >
                        <option value="all">All protocols</option>
                        {Array.from(new Set(rows.map((p) => p.protocol))).map(
                          (p) => (
                            <option key={p} value={p}>
                              {protocolLabel(p)}
                            </option>
                          ),
                        )}
                      </select>
                    </label>
                  </div>
                  <div
                    className="quote-chips"
                    role="group"
                    aria-label="Quote token"
                  >
                    <span>Quoted in</span>
                    {[
                      ["USDG", "USDG"],
                      ["USDC", "USDC"],
                      ["USDT", "USDT"],
                      ["WETH", "WETH"],
                      ["", "Any"],
                    ].map(([value, label]) => (
                      <button
                        key={label}
                        type="button"
                        className={quote === value ? "chip active" : "chip"}
                        disabled={demo && value !== "USDG"}
                        aria-pressed={quote === value}
                        onClick={() => setQuote(value)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <div className="data-panel">
                    <div className="data-toolbar">
                      <div className="panel-title">
                        <span className="status-dot" />
                        {active === "watchlist" ? "Saved pairs" : "Pool book"}
                        <span className="count">{visible.length}</span>
                      </div>
                      <label className="search">
                        <Search size={15} />
                        <input
                          ref={searchRef}
                          aria-label="Search pools"
                          placeholder="WETH, USDG, or address"
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                        />
                        <kbd>/</kbd>
                      </label>
                      <label className="sort-label">
                        <ArrowDownUp size={14} />
                        <select
                          aria-label="Sort pools"
                          value={sort}
                          onChange={(e) => setSort(e.target.value)}
                        >
                          <option value="score">Score</option>
                          <option value="tvl">TVL</option>
                          <option value="volume">Volume</option>
                          <option value="fees">Fees</option>
                          <option value="feeYield">Fee yield</option>
                        </select>
                      </label>
                    </div>
                    {busy ? (
                      <div className="empty" role="status">
                        <RefreshCw className="spinning" />
                        Reading the market…
                      </div>
                    ) : error ? (
                      <div className="empty error" role="alert">
                        {error}
                        <button
                          className="button secondary"
                          onClick={() => setRefresh((n) => n + 1)}
                        >
                          Try again
                        </button>
                      </div>
                    ) : !visible.length ? (
                      <div className="empty">
                        <Search size={28} />
                        <h3>
                          {active === "watchlist"
                            ? "No saved pairs match this view."
                            : "No pairs match these filters."}
                        </h3>
                        <p>
                          {active === "watchlist"
                            ? "Save a pair from the screener, or loosen profile and network."
                            : "Try another quote, protocol, or search."}
                        </p>
                        <button
                          className="button secondary"
                          onClick={() => {
                            setQuery("");
                            setProtocol("all");
                            setSettings({ ...settings, profile: "degen" });
                          }}
                        >
                          Broaden filters
                        </button>
                      </div>
                    ) : (
                      <div
                        className="table-scroll"
                        role="region"
                        aria-label="Ranked liquidity pools"
                        tabIndex={0}
                      >
                        <table className="pool-table">
                          <thead>
                            <tr>
                              <th aria-label="Watchlist" />
                              <th>Pair</th>
                              <SortHeader
                                id="tvl"
                                label="TVL"
                                sort={sort}
                                onSort={setSort}
                              />
                              <SortHeader
                                id="volume"
                                label="24h volume"
                                sort={sort}
                                onSort={setSort}
                                className="col-volume"
                              />
                              <SortHeader
                                id="fees"
                                label="24h fees"
                                sort={sort}
                                onSort={setSort}
                              />
                              <SortHeader
                                id="feeYield"
                                label="Fee yield"
                                sort={sort}
                                onSort={setSort}
                                className="col-yield"
                              />
                              <th>Grade</th>
                              <SortHeader
                                id="score"
                                label="Score"
                                sort={sort}
                                onSort={setSort}
                              />
                              <th aria-label="Details" />
                            </tr>
                          </thead>
                          <tbody>
                            {visible.map((p) => (
                              <tr
                                key={p.id}
                                className={selected === p.id ? "selected" : ""}
                                onClick={(event) => {
                                  if (
                                    (event.target as HTMLElement).closest(
                                      "button, a",
                                    )
                                  )
                                    return;
                                  setSelected(p.id);
                                }}
                              >
                                <td>
                                  <button
                                    className={`icon-button ${watched.includes(p.id) ? "saved" : ""}`}
                                    disabled={mutating}
                                    aria-label={`${watched.includes(p.id) ? "Unwatch" : "Watch"} ${p.pair}`}
                                    onClick={() => toggleWatch(p)}
                                  >
                                    <Bookmark
                                      size={16}
                                      fill={
                                        watched.includes(p.id)
                                          ? "currentColor"
                                          : "none"
                                      }
                                    />
                                  </button>
                                </td>
                                <td>
                                  <button
                                    className="pair-button"
                                    onClick={() => setSelected(p.id)}
                                  >
                                    <PairMark pool={p} quote={quote} />
                                  </button>
                                </td>
                                <td>{money(p.tvl, true)}</td>
                                <td className="col-volume">
                                  {money(p.volume, true)}
                                </td>
                                <td>{money(p.fees, true)}</td>
                                <td className="positive col-yield">
                                  {pct(p.feeYield)}
                                </td>
                                <td>
                                  <span className={`grade grade-${p.grade}`}>
                                    {p.grade}
                                  </span>
                                </td>
                                <td className="amber">
                                  {p.score.toFixed(1)}
                                  <span className="score-track">
                                    <i style={{ width: `${p.score}%` }} />
                                  </span>
                                </td>
                                <td>
                                  <button
                                    className="icon-button"
                                    aria-label={`Details for ${p.pair}`}
                                    onClick={() => setSelected(p.id)}
                                  >
                                    <ChevronRight size={16} />
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    <div className="table-footer">
                      <span>
                        {demo
                          ? "Fixture snapshot · not live"
                          : timestamp
                            ? `Fetched ${new Date(timestamp * 1000).toLocaleTimeString()} · cached up to 90s`
                            : "Awaiting source"}{" "}
                        · {settings.source}
                      </span>
                      <span>
                        {visible.length} pair{visible.length === 1 ? "" : "s"}
                      </span>
                    </div>
                  </div>
                  <div className="risk-note">
                    <ShieldCheck size={16} />
                    <span>
                      Score is a research ranking, not a guarantee. Missing
                      metrics stay unknown — they are not zero. Open a pair
                      before you size it.
                    </span>
                  </div>
                  {pool && (
                    <PoolDetail
                      pool={pool}
                      size={settings.size}
                      watched={watched.includes(pool.id)}
                      busy={mutating}
                      toggle={() => toggleWatch(pool)}
                      close={() => setSelected(null)}
                    />
                  )}
                </>
              )}
              {active === "settings" && (
                <SettingsForm
                  settings={settings}
                  demo={demo}
                  onSave={setSettings}
                />
              )}
              {["positions", "leaderboard"].includes(active) && (
                <ResearchPanel
                  kind={active}
                  settings={settings}
                  demo={demo}
                  refresh={refresh}
                />
              )}
            </>
          )}
          <div role="status" className="form-status">
            {notice}
          </div>
        </main>
        <footer className="app-footer">
          <span>
            Curator <span className="muted">/ independent LP research</span>
          </span>
          <Link href="/">How Curator works ↗</Link>
        </footer>
      </div>
    </div>
  );
}
function SortHeader({
  id,
  label,
  sort,
  onSort,
  className = "",
}: {
  id: string;
  label: string;
  sort: string;
  onSort: (id: string) => void;
  className?: string;
}) {
  const active = sort === id;
  return (
    <th className={className} aria-sort={active ? "descending" : "none"}>
      <button type="button" className="sort-head" onClick={() => onSort(id)}>
        {label}
        {active ? " ↓" : ""}
      </button>
    </th>
  );
}
function Metric({
  label,
  value,
  note,
  accent = false,
}: {
  label: string;
  value: string;
  note: string;
  accent?: boolean;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={accent ? "amber capitalize" : ""}>{value}</strong>
      <small>{note}</small>
    </div>
  );
}
function PoolDetail({
  pool: p,
  size,
  watched,
  busy,
  toggle,
  close,
}: {
  pool: Pool;
  size: number;
  watched: boolean;
  busy: boolean;
  toggle: () => void;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = dialog.current;
    el?.showModal();
    return () => {
      el?.close();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="detail-dialog"
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="detail-inner">
        <header className="detail-sticky">
          <div className="detail-sticky-bar">
            <span className="eyebrow">Pool · {p.source}</span>
            <button
              autoFocus
              className="icon-button"
              onClick={close}
              aria-label="Close pool details"
            >
              <X size={20} />
            </button>
          </div>
          <h2 className="detail-pair">
            <PairMark pool={p} size="lg" />
          </h2>
        </header>
        <p className="mono muted">
          {chains[p.chain as keyof typeof chains] || p.chain}
        </p>
        <code className="address">{p.address}</code>
        <div className="detail-score">
          <strong>
            {p.score.toFixed(1)}
            <small>/100</small>
          </strong>
          <span>
            Curator score
            <br />
            <span className={`grade grade-${p.grade}`}>Grade {p.grade}</span>
          </span>
        </div>
        <div className="parts">
          {Object.entries(p.parts).map(([key, value]) => (
            <div key={key}>
              <span>{key}</span>
              <meter min={0} max={1} value={value} />
              <span>{Math.round(value * 100)}</span>
            </div>
          ))}
        </div>
        <div className="detail-metrics">
          <Metric
            label="24h fees"
            value={money(p.fees)}
            note="Pool-wide, before your share"
          />
          <Metric
            label="Volatility"
            value={pct(p.volatility)}
            note="Daily σ assumption unverified"
          />
          <Metric
            label="24h drawdown"
            value={pct(p.drawdown)}
            note="Source-reported"
          />
          <Metric
            label="24h volume"
            value={money(p.volume, true)}
            note={p.tvlBasis || "Source-reported"}
          />
        </div>
        <h3>
          At your size <span className="amber">{money(size)}</span>
        </h3>
        <dl className="simulation">
          <div>
            <dt>Estimated fees / day</dt>
            <dd>{money(p.sim.fee_day)}</dd>
          </div>
          <div>
            <dt>Estimated IL / day</dt>
            <dd>{money(p.sim.il_day)}</dd>
          </div>
          <div>
            <dt>Estimated net / day</dt>
            <dd>{money(p.sim.net_day)}</dd>
          </div>
          <div>
            <dt>Share after deposit</dt>
            <dd>{pct((p.sim.share || 0) * 100)}</dd>
          </div>
        </dl>
        <p className="fine-print">
          Simulation assumes the last 24h repeats. Impermanent loss uses a
          full-range model and an unverified daily volatility assumption. Gas,
          execution costs, and future price changes are not included.
        </p>
        {(p.sim.share || 0) >= 0.25 && (
          <p className="notice">
            Heavy concentration: your deposit would represent at least 25% of
            this pool.
          </p>
        )}
        <div className="flags">
          {p.flags.map((f) => (
            <span key={f}>{f}</span>
          ))}
        </div>
        {p.unknown.length > 0 && (
          <p className="notice">
            Unknown metrics: {p.unknown.join(", ")}. Unknown does not mean zero
            risk.
          </p>
        )}
        {p.risks.map((r) => (
          <p key={r} className="notice">
            {r}
          </p>
        ))}
        <div className="detail-actions">
          <button className="button" disabled={busy} onClick={toggle}>
            {watched ? <Check size={16} /> : <Bookmark size={16} />}{" "}
            {watched ? "Saved to watchlist" : "Save to watchlist"}
          </button>
          <a
            href={p.url}
            target="_blank"
            rel="noreferrer"
            className="text-link"
          >
            View on Krystal <ArrowUpRight size={15} />
          </a>
        </div>
      </div>
    </dialog>
  );
}
function SettingsForm({
  settings,
  demo,
  onSave,
}: {
  settings: Settings;
  demo: boolean;
  onSave: (s: Settings) => void;
}) {
  const [draft, setDraft] = useState(settings);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      if (!demo)
        await request("/api/account", {
          method: "POST",
          body: JSON.stringify({ action: "settings", settings: draft }),
        });
      onSave(draft);
      setMessage(
        demo
          ? "Demo preferences updated for this visit."
          : "Preferences saved.",
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="settings-panel" onSubmit={submit}>
      <div className="eyebrow">Account</div>
      <h2>Workspace defaults.</h2>
      <p>
        Profile, network, and simulation size belong to this account. Provider
        credentials stay on the server.
      </p>
      <label>
        Default risk profile
        <select
          value={draft.profile}
          onChange={(e) => setDraft({ ...draft, profile: e.target.value })}
        >
          {profiles.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
      </label>
      <label>
        Default network
        <select
          disabled={demo}
          value={draft.chain}
          onChange={(e) =>
            setDraft({
              ...draft,
              chain: Number(e.target.value),
              source: "krystal",
            })
          }
        >
          {Object.entries(chains).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label>
        Data source
        <select
          disabled={demo}
          value={draft.source}
          onChange={(e) => setDraft({ ...draft, source: e.target.value })}
        >
          <option value="krystal">Krystal</option>
          {draft.chain === 4663 && <option value="rhpools">rhpools</option>}
        </select>
      </label>
      <label>
        Simulation size (USD)
        <input
          type="number"
          disabled={demo}
          required
          min={1}
          max={100000000}
          step="any"
          value={draft.size}
          onChange={(e) => setDraft({ ...draft, size: Number(e.target.value) })}
        />
      </label>
      <label>
        Wallet to monitor
        <input
          placeholder="0x…"
          maxLength={42}
          pattern="0x[a-fA-F0-9]{40}"
          value={draft.wallet}
          onChange={(e) => setDraft({ ...draft, wallet: e.target.value })}
        />
        <small>
          Public address only. Curator never asks for a private key.
        </small>
      </label>
      {demo && (
        <p className="fine-print">
          The demo uses Robinhood / Krystal and a fixed $10,000 simulation.
        </p>
      )}
      <button className="button" disabled={busy}>
        {busy ? "Saving…" : "Save preferences"} <Check size={16} />
      </button>
      <p role="status">{message}</p>
    </form>
  );
}
type VaultPosition = {
  id: string;
  token0: string;
  token1: string;
  status: string;
  value: number;
  pnl: number;
  fee_pending: number;
  min_price: number;
  max_price: number;
  current_price: number | null;
};
type Vault = {
  address: string;
  name: string;
  tvl: number;
  pnl: number;
  my_value: number;
  earning_24h: number;
  positions: VaultPosition[];
  url: string;
  chain_id: number;
};
type RankedVault = {
  vault: Vault;
  roi_pct: number;
  candidate: boolean;
  why_not: string[];
  url: string;
};
type Evaluation = {
  verdict: string;
  reasons: string[];
  checks: {
    key: string;
    result: string;
    rule: string;
    evidence: string;
    basis: string;
  }[];
};
function ResearchPanel({
  kind,
  settings,
  demo,
  refresh,
}: {
  kind: string;
  settings: Settings;
  demo: boolean;
  refresh: number;
}) {
  const [vaults, setVaults] = useState<Vault[]>([]);
  const [ranked, setRanked] = useState<RankedVault[]>([]);
  const [owners, setOwners] = useState<
    {
      address: string;
      name: string;
      tvl: number;
      pnl: number;
      roi: number;
      vaults: number;
    }[]
  >([]);
  const [boardView, setBoardView] = useState("vaults");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [time, setTime] = useState<number | null>(null);
  const [review, setReview] = useState<Evaluation | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    const id = ++generation.current;
    setError("");
    setVaults([]);
    setRanked([]);
    setOwners([]);
    setReview(null);
    setReviewBusy(false);
    setTime(null);
    if (demo || (kind === "positions" && !settings.wallet)) return;
    setBusy(true);
    const params = new URLSearchParams({ chain: String(settings.chain) });
    if (kind === "positions") params.set("wallet", settings.wallet);
    request(`/api/market/${kind}?${params}`)
      .then((data) => {
        if (id !== generation.current) return;
        if (kind === "positions") setVaults(data.rows);
        else {
          setRanked(data.rows);
          setOwners(data.owners || []);
        }
        setTime(data.fetchedAt);
      })
      .catch((e) => {
        if (id === generation.current) setError(e.message);
      })
      .finally(() => {
        if (id === generation.current) setBusy(false);
      });
    return () => {
      generation.current++;
    };
  }, [kind, settings.chain, settings.wallet, demo, refresh]);
  async function inspect(v: Vault) {
    const id = generation.current;
    setReviewBusy(true);
    setReview(null);
    setError("");
    try {
      const data = await request(
        `/api/market/review?chain=${v.chain_id}&address=${encodeURIComponent(v.address)}`,
      );
      if (id === generation.current) setReview(data.evaluation);
    } catch (e) {
      if (id === generation.current)
        setError(e instanceof Error ? e.message : "Review unavailable.");
    } finally {
      if (id === generation.current) setReviewBusy(false);
    }
  }
  if (demo)
    return (
      <div className="empty panel">
        <Layers3 size={32} />
        <h2>Sign in to connect this view.</h2>
        <p>
          {kind === "positions"
            ? "Save a public wallet to inspect its Krystal vault LP positions."
            : "Sign in to browse live public vault rankings and request a rule-based review."}
        </p>
        <Link className="button" href="/login">
          Open your workspace <ArrowUpRight size={16} />
        </Link>
        <small>
          The demo does not invent wallet balances or vault returns.
        </small>
      </div>
    );
  if (kind === "positions" && !settings.wallet)
    return (
      <div className="empty panel">
        <Wallet size={32} />
        <h2>Add a wallet to start.</h2>
        <p>
          Save a public wallet address in settings. No wallet signature
          required.
        </p>
        <Link className="button" href="/app/settings">
          Add wallet <ArrowUpRight size={16} />
        </Link>
      </div>
    );
  return (
    <div className="research">
      <p className="fine-print">
        {kind === "positions"
          ? "Krystal vault positions for your saved wallet; standalone wallet LP NFTs are not included."
          : "Public Krystal vaults. ROI uses lifetime deposits; it is a comparison, not reconciled P&L. Candidate status is a shortlist filter, not approval."}
      </p>
      {busy && (
        <div className="empty" role="status">
          Reading the source…
        </div>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {!busy && !error && !(kind === "positions" ? vaults : ranked).length && (
        <div className="empty panel">
          No {kind === "positions" ? "vault positions" : "public vaults"} found
          for this network.
        </div>
      )}
      {kind === "leaderboard" && (
        <div className="board-tabs" role="group" aria-label="Leaderboard view">
          <button
            className={
              boardView === "vaults" ? "button small" : "button secondary small"
            }
            onClick={() => setBoardView("vaults")}
          >
            Vaults
          </button>
          <button
            className={
              boardView === "owners" ? "button small" : "button secondary small"
            }
            onClick={() => setBoardView("owners")}
          >
            Owners
          </button>
        </div>
      )}
      {kind === "positions" ? (
        vaults.map((v) => (
          <article key={v.address} className="vault-card">
            <header>
              <h2>{v.name}</h2>
              <a
                className="text-link"
                href={v.url}
                target="_blank"
                rel="noreferrer"
              >
                View vault <ArrowUpRight size={15} />
              </a>
            </header>
            <div className="metric-grid">
              <Metric
                label="YOUR VALUE"
                value={money(v.my_value)}
                note="Source-reported wallet value"
              />
              <Metric
                label="VAULT TVL"
                value={money(v.tvl, true)}
                note="All depositors"
              />
              <Metric
                label="VAULT PNL"
                value={money(v.pnl)}
                note="Source-reported aggregate"
              />
              <Metric
                label="24H EARNINGS"
                value={money(v.earning_24h)}
                note="Vault-wide earnings"
              />
            </div>
            {v.positions.map((p) => (
              <div className="position-row" key={p.id}>
                <PairMark
                  pool={{
                    pair: `${p.token0}/${p.token1}`,
                    token0: p.token0,
                    token1: p.token1,
                    protocol: "",
                  }}
                  showMeta={false}
                />
                <span
                  className={p.status === "IN_RANGE" ? "positive" : "amber"}
                >
                  {p.status.replaceAll("_", " ")}
                </span>
                <span>Value {money(p.value)}</span>
                <span>PnL {money(p.pnl)}</span>
                <span>Pending fees {money(p.fee_pending)}</span>
                <small>
                  Range {p.min_price.toPrecision(4)} –{" "}
                  {p.max_price.toPrecision(4)} · Price{" "}
                  {p.current_price?.toPrecision(4) ?? "Unknown"}
                </small>
              </div>
            ))}
          </article>
        ))
      ) : boardView === "owners" ? (
        <div
          className="data-panel table-scroll"
          role="region"
          aria-label="Owner rankings"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th>OWNER</th>
                <th>VAULTS</th>
                <th>TVL</th>
                <th>PNL</th>
                <th>ROI</th>
              </tr>
            </thead>
            <tbody>
              {owners.map((o) => (
                <tr key={o.address}>
                  <td>
                    <strong>{o.name}</strong>
                    <small>
                      {o.address.slice(0, 8)}…{o.address.slice(-6)}
                    </small>
                  </td>
                  <td>{o.vaults}</td>
                  <td>{money(o.tvl, true)}</td>
                  <td>{money(o.pnl)}</td>
                  <td>{pct(o.roi)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!owners.length && !busy && (
            <div className="empty">No owners meet the ranking criteria.</div>
          )}
        </div>
      ) : (
        <div
          className="data-panel table-scroll"
          role="region"
          aria-label="Vault rankings"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th>VAULT</th>
                <th>TVL</th>
                <th>ROI</th>
                <th>SHORTLIST</th>
                <th>REVIEW</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((r) => (
                <tr key={r.vault.address}>
                  <td>
                    <strong>{r.vault.name}</strong>
                    <small>
                      {r.vault.address.slice(0, 8)}…{r.vault.address.slice(-6)}
                    </small>
                  </td>
                  <td>{money(r.vault.tvl, true)}</td>
                  <td>{pct(r.roi_pct)}</td>
                  <td>
                    {r.candidate ? (
                      <span className="positive">Candidate</span>
                    ) : (
                      r.why_not[0]
                    )}
                  </td>
                  <td>
                    <button
                      className="button secondary small"
                      disabled={reviewBusy}
                      onClick={() => inspect(r.vault)}
                    >
                      Review <ArrowUpRight size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {reviewBusy && <p role="status">Reviewing vault evidence…</p>}
      {review && (
        <section className="vault-card">
          <div className="eyebrow">RULE-BASED REVIEW</div>
          <h2>{review.verdict.replaceAll("_", " ")}</h2>
          {review.reasons.map((r) => (
            <p key={r}>{r}</p>
          ))}
          {review.checks.map((c) => (
            <div key={c.key} className="review-check">
              <strong>
                {c.result.toUpperCase()} · {c.rule}
              </strong>
              <p>{c.evidence}</p>
              <small>Evidence basis: {c.basis}</small>
            </div>
          ))}
        </section>
      )}
      {time && (
        <p className="fine-print">
          Fetched {new Date(time * 1000).toLocaleString()} ·{" "}
          {kind === "positions" ? "90-second" : "5-minute"} cache
        </p>
      )}
    </div>
  );
}
