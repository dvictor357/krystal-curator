"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { addressActions, withRef } from "@/lib/links";
import { useEffect, useMemo, useRef, useState } from "react";
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
  MoreHorizontal,
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
import { clearResources, useResource } from "@/lib/resource";
import { clearSignedInHint } from "@/lib/session";
import { StatusBar } from "@/components/statusbar";
import { Pager } from "@/components/pager";
import { AmbientField } from "@/components/ambient";
import { TrackRecord } from "@/components/track-record";
import { PaletteProvider } from "@/components/palette";
import { AddressChip, TokenLink } from "@/components/address";
import { usePalette } from "@/components/palette";
import { usePagination } from "@/lib/paging";
import { shortAddress } from "@/lib/siwe";
import { protocolLabel } from "@/lib/pair";
import { chains, profiles, defaultQuote, quotesFor } from "@/lib/validation";
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
  const [address, setAddress] = useState("");
  const [settings, setSettings] = useState<Settings>(defaults);
  const [watched, setWatched] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [protocol, setProtocol] = useState("all");
  const [quote, setQuote] = useState(defaultQuote(defaults.chain));
  // A new network gets its own quote token; the old one usually does not exist there.
  useEffect(() => {
    setQuote(defaultQuote(settings.chain));
  }, [settings.chain]);
  const [sort, setSort] = useState("score");
  const [accountError, setAccountError] = useState("");
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [mutating, setMutating] = useState(false);
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
          setEmail(account.email ?? shortAddress(account.address));
          setAddress(account.address ?? "");
          setSettings(account.settings || defaults);
          setWatched(account.watchlist);
          setReady(true);
        }
      })
      .catch((e) => {
        if (!cancelled) setAccountError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [demo]);
  const poolsPath =
    !demo && ready && ["screener", "watchlist"].includes(active)
      ? `/api/market/pools?${new URLSearchParams({
          chain: String(settings.chain),
          source: settings.source,
          profile: settings.profile,
          size: String(settings.size),
          quote: quote || "any",
        })}`
      : null;
  const pools = useResource<{ rows: Pool[]; fetchedAt: number }>(poolsPath, {
    ttl: 60,
    interval: 60,
  });
  const rows: Pool[] = demo
    ? (snapshot[settings.profile as keyof typeof snapshot] as Pool[])
    : (pools.data?.rows ?? []);
  const busy = pools.busy;
  const error = accountError || pools.error;
  const timestamp = pools.fetchedAt;
  useEffect(() => {
    setSelected(null);
  }, [poolsPath]);
  // Deep link from a rotation candidate: /app?pool=<id> opens that pool's detail.
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("pool");
    if (!wanted || !rows.some((p) => p.id === wanted)) return;
    setProtocol("all");
    setQuery("");
    setSelected(wanted);
    window.history.replaceState(null, "", window.location.pathname);
  }, [rows]);
  useEffect(() => {
    if (refresh && poolsPath) pools.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh]);

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
  const paging = usePagination(
    visible,
    `${active}:${quote}:${protocol}:${sort}:${query}`,
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
    <PaletteProvider>
      <div className="workspace">
        <AmbientField />
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
              <AccountCard
                email={email}
                address={address}
                chain={settings.chain}
                signOut={() =>
                  request("/api/auth/logout", { method: "POST" })
                    .then(() => {
                      clearResources();
                      clearSignedInHint();
                      window.location.assign("/login");
                    })
                    .catch((e) => setNotice(e.message))
                }
              />
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
                  .then(() => {
                    clearResources();
                    clearSignedInHint();
                    window.location.assign("/login");
                  })
                  .catch((e) => setNotice(e.message))
              }
            >
              <LogOut size={14} /> Sign out
            </button>
          )}
          <main id="main" className="app-content page-enter" key={active}>
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
                  <RefreshCw
                    size={15}
                    className={busy || pools.revalidating ? "spinning" : ""}
                  />
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
                      <SizeMetric
                        size={settings.size}
                        demo={demo}
                        onChange={(size) => {
                          const next = { ...settings, size };
                          setSettings(next);
                          if (!demo)
                            request("/api/account", {
                              method: "POST",
                              body: JSON.stringify({
                                action: "settings",
                                settings: next,
                              }),
                            }).catch((e) => setNotice(e.message));
                        }}
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
                        <span>Risk profile</span>
                        <select
                          aria-label="Risk profile"
                          value={settings.profile}
                          onChange={(e) =>
                            setSettings({
                              ...settings,
                              profile: e.target.value,
                            })
                          }
                        >
                          {profiles.map((p) => (
                            <option key={p} value={p}>
                              {p.charAt(0).toUpperCase() + p.slice(1)}
                            </option>
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
                      {quotesFor(settings.chain).map(([value, label]) => (
                        <button
                          key={label}
                          type="button"
                          className={quote === value ? "chip active" : "chip"}
                          disabled={demo && value !== defaultQuote(4663)}
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
                          className="table-scroll standard"
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
                              {paging.rows.map((p) => (
                                <tr
                                  key={p.id}
                                  className={
                                    selected === p.id ? "selected" : ""
                                  }
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
                      <Pager
                        paging={paging}
                        unit="pairs"
                        note={
                          <>
                            {demo
                              ? "Fixture snapshot · not live"
                              : timestamp
                                ? `Fetched ${new Date(timestamp * 1000).toLocaleTimeString()} · refreshes every 60s`
                                : "Awaiting source"}{" "}
                            · {settings.source}
                          </>
                        }
                      />
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
          <StatusBar demo={demo} />
          <footer className="app-footer">
            <span>
              Curator <span className="muted">/ independent LP research</span>
            </span>
            <span className="footer-links">
              <Link href="/">How Curator works ↗</Link>
              <Link href="/terms">Terms</Link>
              <Link href="/privacy">Privacy</Link>
            </span>
          </footer>
        </div>
      </div>
    </PaletteProvider>
  );
}
/** Signed-in card: opens the wallet palette with Settings and Sign out at the end. */
function AccountCard({
  email,
  address,
  chain,
  signOut,
}: {
  email: string;
  address: string;
  chain: number;
  signOut: () => void;
}) {
  const open = usePalette();
  const router = useRouter();
  return (
    <button
      className="account-card"
      onClick={() =>
        open({
          title: "Your account",
          subtitle: address || email,
          actions: [
            ...(address ? addressActions("wallet", address, chain) : []),
            {
              id: "settings",
              kind: "run",
              label: "Settings",
              hint: "profile · network · alerts",
              run: () => router.push("/app/settings"),
            },
            {
              id: "signout",
              kind: "run",
              label: "Sign out",
              hint: "end this session",
              run: signOut,
              danger: true,
            },
          ],
        })
      }
    >
      <span className="avatar">
        {email.startsWith("0x") ? "0x" : email.slice(0, 1).toUpperCase()}
      </span>
      <span className="account-email">
        {email}
        <small>Account · actions</small>
      </span>
      <MoreHorizontal size={15} />
    </button>
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
/** Simulation size as a header metric you can edit in place; persists with the account. */
function SizeMetric({
  size,
  demo,
  onChange,
}: {
  size: number;
  demo: boolean;
  onChange: (size: number) => void;
}) {
  const [draft, setDraft] = useState(String(size));
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    if (!editing) setDraft(String(size));
  }, [size, editing]);
  function commit() {
    setEditing(false);
    const n = Number(draft.replace(/[^0-9.]/g, ""));
    if (Number.isFinite(n) && n >= 1 && n <= 100_000_000 && n !== size)
      onChange(n);
    else setDraft(String(size));
  }
  return (
    <div className="metric metric-size">
      <span>Simulation size</span>
      <label className="size-input">
        <b>$</b>
        <input
          aria-label="Simulation size in USD"
          inputMode="decimal"
          disabled={demo}
          value={editing ? draft : size.toLocaleString("en-US")}
          onFocus={(e) => {
            setEditing(true);
            setDraft(String(size));
            e.currentTarget.select();
          }}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") {
              setDraft(String(size));
              setEditing(false);
              e.currentTarget.blur();
            }
          }}
        />
      </label>
      <small className="size-presets">
        {[1000, 5000, 10000, 50000].map((n) => (
          <button
            key={n}
            type="button"
            className={n === size ? "on" : ""}
            disabled={demo}
            onClick={() => onChange(n)}
          >
            {n >= 1000 ? `${n / 1000}k` : n}
          </button>
        ))}
        <span>· fees, IL and share at this size</span>
      </small>
    </div>
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
  const [closing, setClosing] = useState(false);
  useEffect(() => {
    const el = dialog.current;
    el?.showModal();
    return () => {
      el?.close();
    };
  }, []);
  // Play the slide-out, then let the parent unmount us.
  function dismiss() {
    if (closing) return;
    setClosing(true);
    const el = dialog.current;
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (!el || reduced) return close();
    const done = () => {
      el.removeEventListener("animationend", done);
      close();
    };
    el.addEventListener("animationend", done);
    window.setTimeout(done, 400); // safety if the animation never fires
  }
  return (
    <dialog
      ref={dialog}
      className={`detail-dialog${closing ? " closing" : ""}`}
      onCancel={(e) => {
        e.preventDefault();
        dismiss();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) dismiss();
      }}
    >
      <div className="detail-inner">
        <header className="detail-sticky">
          <div className="detail-sticky-bar">
            <span className="eyebrow">Pool · {p.source}</span>
            <button
              autoFocus
              className="icon-button"
              onClick={dismiss}
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
        <div className="detail-addresses">
          <AddressChip
            address={p.address}
            chain={p.chain}
            kind="pool"
            label={`${p.pair} · pool`}
            krystalUrl={p.url}
            full
          />
          <span className="detail-tokens">
            <TokenLink
              symbol={p.token0 ?? ""}
              address={p.token0Address}
              chain={p.chain}
            />
            <span className="pair-slash">/</span>
            <TokenLink
              symbol={p.token1 ?? ""}
              address={p.token1Address}
              chain={p.chain}
            />
            <small>token contracts</small>
          </span>
        </div>
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
            href={withRef(p.url)}
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
  const [testing, setTesting] = useState(false);
  async function testTelegram() {
    setTesting(true);
    setMessage("");
    try {
      await request("/api/account", {
        method: "POST",
        body: JSON.stringify({
          action: "telegram_test",
          chatId: draft.telegram_chat_id,
        }),
      });
      setMessage("Test message sent. Save to keep alerts on for this chat.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not send the test.");
    } finally {
      setTesting(false);
    }
  }
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
            <option key={p} value={p}>
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </option>
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
      <fieldset className="alerts-box">
        <legend>Alerts · Telegram</legend>
        <label>
          Telegram chat ID
          <span className="field-row">
            <input
              placeholder="e.g. 123456789"
              maxLength={32}
              pattern="-?[0-9]{1,20}"
              disabled={demo}
              value={draft.telegram_chat_id}
              onChange={(e) =>
                setDraft({ ...draft, telegram_chat_id: e.target.value })
              }
            />
            <button
              type="button"
              className="button secondary small"
              disabled={
                demo || testing || !/^-?\d{1,20}$/.test(draft.telegram_chat_id)
              }
              onClick={testTelegram}
            >
              {testing ? "Sending…" : "Send test"}
            </button>
          </span>
          <small>
            Open the Curator bot in Telegram, press Start, then paste your chat
            ID (from @userinfobot). Alerts: out of range, edge within 0.5σ, pool
            grade decay, PnL drop ≥ 5%, and rotation verdicts opening or
            closing. Checked every 5 minutes.
          </small>
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            disabled={demo}
            checked={draft.alerts}
            onChange={(e) => setDraft({ ...draft, alerts: e.target.checked })}
          />
          Send alerts for the wallet above
        </label>
      </fieldset>
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
  pool_address: string;
  token0: string;
  token1: string;
  protocol: string;
  status: string;
  value: number;
  deposit: number;
  pnl: number;
  roi_pct: number;
  il: number;
  fee_pending: number;
  fee_claimed: number;
  fee_apr: number;
  total_apr: number;
  min_price: number;
  max_price: number;
  current_price: number | null;
  opened_ts: number;
};
/** Prices across many magnitudes without exponent notation. */
function price(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1000)
    return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (abs >= 1)
    return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return value.toLocaleString("en-US", { maximumSignificantDigits: 4 });
}
function ageLabel(openedTs: number) {
  if (!openedTs) return "";
  const days = (Date.now() / 1000 - openedTs) / 86400;
  if (days < 1) return `${Math.max(1, Math.round(days * 24))}h`;
  if (days < 60) return `${Math.round(days)}d`;
  return `${Math.round(days / 30)}mo`;
}
function signed(value: number) {
  return `${value > 0 ? "+" : ""}${money(value)}`;
}
/** Where the current price sits inside the position's range; clamps when out of range. */
function RangeBar({ p }: { p: VaultPosition }) {
  const span = p.max_price - p.min_price;
  const at =
    p.current_price == null || span <= 0
      ? null
      : Math.min(1, Math.max(0, (p.current_price - p.min_price) / span));
  const inRange = p.status === "IN_RANGE";
  const below = p.current_price != null && p.current_price < p.min_price;
  const above = p.current_price != null && p.current_price > p.max_price;
  // Half-width of the range around its midpoint: how much room the position has.
  const mid = (p.min_price + p.max_price) / 2;
  const width =
    span > 0 && mid > 0 ? `±${((span / 2 / mid) * 100).toFixed(0)}%` : "";
  return (
    <div
      className={`range-bar ${inRange ? "in" : "out"}`}
      role="img"
      aria-label={`Range ${price(p.min_price)} to ${price(p.max_price)}, price ${price(p.current_price)}`}
    >
      <div className="range-track">
        <span className="range-fill" />
        {at != null && (
          <span
            className={`range-marker${below ? " below" : ""}${above ? " above" : ""}`}
            style={{ left: `${at * 100}%` }}
          />
        )}
      </div>
      <div className="range-labels">
        <span>{price(p.min_price)}</span>
        <span className="range-now">
          {price(p.current_price)}
          {width && <small>{width}</small>}
        </span>
        <span>{price(p.max_price)}</span>
      </div>
    </div>
  );
}
type Candidate = {
  pair: string;
  poolId: string;
  address: string;
  chain: number;
  url: string;
  protocol: string;
  grade: string;
  feeDay: number;
  feeDay24h: number;
  feeDay7d: number | null;
  spike: boolean;
  ilDay: number;
  netDay: number;
  share: number;
  upliftDay: number;
  paybackDays: number | null;
  sigmaKnown: boolean;
};
type RotationRow = {
  id: string;
  pair: string;
  value: number;
  cost: number;
  kind: "rotate" | "consider" | "stay" | "none";
  verdict: string;
  current: {
    grade: string | null;
    address: string;
    chain: number;
    url: string;
    poolId: string | null;
    feeDay: number;
    ilDay: number | null;
    netDay: number;
    share: number | null;
    sigmaKnown: boolean;
    inScreener: boolean;
  };
  best: {
    pair: string;
    poolId: string;
    grade: string;
    tvl: number;
    spike: boolean;
    upliftDay: number;
    paybackDays: number | null;
  } | null;
  edge: {
    name: string;
    distPct: number;
    sigmas: number | null;
    days: number | null;
    urgency: string;
  } | null;
  candidates: Candidate[];
  history: {
    since: number;
    count: number;
    previous: { kind: string; bestPool: string; at: number } | null;
    outcome: {
      at: number;
      days: number;
      kind: string;
      bestPool: string;
      predictedNetDay: number;
      predictedUpliftDay: number;
      realisedFeeDay: number;
    } | null;
  } | null;
};
function agoShort(ts: number) {
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} d`;
}
function days(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value < 0.1) return "<0.1 d";
  return `${value.toFixed(1)} d`;
}
/** Verdict line under a position; expands into the candidate table. */
function RotationVerdict({
  r,
  open,
  toggle,
}: {
  r: RotationRow;
  open: boolean;
  toggle: () => void;
}) {
  const palette = usePalette();
  const router = useRouter();
  function poolActions(
    pair: string,
    poolId: string | null,
    address: string,
    chain: number,
    url: string,
  ) {
    palette({
      title: `${pair} · pool`,
      subtitle: address,
      actions: [
        ...(poolId
          ? [
              {
                id: "inspect",
                kind: "run" as const,
                label: "Inspect in screener",
                hint: "score · simulation · risk flags",
                run: () =>
                  router.push(`/app?pool=${encodeURIComponent(poolId)}`),
              },
            ]
          : []),
        ...addressActions("pool", address, chain, { krystalUrl: url }),
      ],
    });
  }
  const label =
    r.kind === "rotate"
      ? "Rotate"
      : r.kind === "consider"
        ? "Consider"
        : r.kind === "stay"
          ? "Stay"
          : "No candidate";
  return (
    <div className="rotation">
      <button
        className={`rotation-line ${r.kind}`}
        onClick={toggle}
        aria-expanded={open}
      >
        <span className={`verdict-pill ${r.kind}`}>{label}</span>
        <span className="rotation-text">
          {r.best && r.kind !== "none" ? (
            <>
              {r.kind === "stay" ? "Best alternative " : "→ "}
              <b>{r.best.pair}</b>
              {" · "}
              <span className={r.best.upliftDay > 0 ? "positive" : "amber"}>
                {signed(r.best.upliftDay)}/d
              </span>
              {r.best.paybackDays != null && (
                <> · pays back in {days(r.best.paybackDays)}</>
              )}
            </>
          ) : (
            r.verdict
          )}
        </span>
        <span className="rotation-meta">
          {r.best && r.kind !== "none" && r.best.spike && (
            <span
              className="amber"
              title="24h fees far above the 7d average; planned on the 7d number"
            >
              24h spike
            </span>
          )}
          {r.best &&
            r.kind !== "none" &&
            r.current.grade &&
            r.best.grade > r.current.grade && (
              <span
                className="amber"
                title="The alternative scores worse than your current pool in this profile"
              >
                grade {r.best.grade} vs your {r.current.grade}
              </span>
            )}
          {!r.current.sigmaKnown && (
            <span
              className="amber"
              title="Current pool volatility unknown; IL estimate is neutral"
            >
              σ?
            </span>
          )}
          {r.edge && r.edge.urgency !== "ok" && r.edge.urgency !== "?" && (
            <span className={r.edge.urgency === "CRITICAL" ? "amber" : ""}>
              {r.edge.name} edge {r.edge.distPct.toFixed(1)}%
              {r.edge.sigmas != null ? ` ≈ ${r.edge.sigmas.toFixed(1)}σ` : ""}
            </span>
          )}
          {r.history && r.history.count > 1 && (
            <span title={`Same verdict for ${agoShort(r.history.since)}`}>
              since {agoShort(r.history.since)}
            </span>
          )}
          <span>switch cost {money(r.cost)}</span>
          <ChevronRight
            size={12}
            className={`rotation-chevron${open ? " open" : ""}`}
          />
        </span>
      </button>
      {open && (
        <div className="table-scroll rotation-table">
          <table>
            <thead>
              <tr>
                <th>POOL</th>
                <th>GRADE</th>
                <th>FEES/D</th>
                <th>IL/D</th>
                <th>NET/D</th>
                <th>SHARE</th>
                <th>UPLIFT</th>
                <th>PAYBACK</th>
              </tr>
            </thead>
            <tbody>
              <tr
                className="rotation-current clickable"
                onClick={() =>
                  poolActions(
                    r.pair,
                    r.current.poolId,
                    r.current.address,
                    r.current.chain,
                    r.current.url,
                  )
                }
              >
                <td>
                  <strong>{r.pair}</strong>
                  <small>current · realised fees</small>
                </td>
                <td>{r.current.grade ?? "—"}</td>
                <td>{money(r.current.feeDay)}</td>
                <td>
                  {r.current.ilDay == null ? "—" : money(r.current.ilDay)}
                </td>
                <td className={r.current.netDay >= 0 ? "positive" : "amber"}>
                  {signed(r.current.netDay)}
                </td>
                <td>
                  {r.current.share == null
                    ? "—"
                    : `${(r.current.share * 100).toFixed(1)}%`}
                </td>
                <td>—</td>
                <td>—</td>
              </tr>
              {r.candidates.map((c) => (
                <tr
                  key={c.poolId}
                  className="clickable"
                  onClick={() =>
                    poolActions(c.pair, c.poolId, c.address, c.chain, c.url)
                  }
                >
                  <td>
                    <strong>{c.pair}</strong>
                    <small>
                      {protocolLabel(c.protocol)}
                      {!c.sigmaKnown ? " · σ?" : ""}
                    </small>
                  </td>
                  <td>{c.grade}</td>
                  <td>
                    {money(c.feeDay)}
                    <small>
                      24h {money(c.feeDay24h)}
                      {c.feeDay7d != null ? ` · 7d ${money(c.feeDay7d)}` : ""}
                      {c.spike ? " · spike" : ""}
                    </small>
                  </td>
                  <td>{money(c.ilDay)}</td>
                  <td className={c.netDay >= 0 ? "positive" : "amber"}>
                    {signed(c.netDay)}
                  </td>
                  <td className={c.share > 0.25 ? "amber" : ""}>
                    {(c.share * 100).toFixed(1)}%
                  </td>
                  <td className={c.upliftDay > 0 ? "positive" : "amber"}>
                    {signed(c.upliftDay)}
                  </td>
                  <td>{days(c.paybackDays)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {r.history?.outcome && (
            <p className="rotation-record">
              <span className="eyebrow">Track record</span>
              {agoShort(r.history.outcome.at)} ago we said{" "}
              <b>{r.history.outcome.kind.toUpperCase()}</b>
              {r.history.outcome.bestPool && r.history.outcome.kind !== "stay"
                ? ` → ${r.history.outcome.bestPool} (+${money(r.history.outcome.predictedUpliftDay)}/d)`
                : ""}
              , expecting {signed(r.history.outcome.predictedNetDay)}/d net from
              staying. Since then this position earned{" "}
              <b
                className={
                  r.history.outcome.realisedFeeDay >=
                  r.history.outcome.predictedNetDay
                    ? "positive"
                    : "amber"
                }
              >
                {money(r.history.outcome.realisedFeeDay)}/d
              </b>{" "}
              in fees over {r.history.outcome.days.toFixed(1)} d.
              {r.history.previous && (
                <>
                  {" "}
                  Before that: {r.history.previous.kind} (
                  {agoShort(r.history.previous.at)} ago).
                </>
              )}
            </p>
          )}
          <p className="fine-print rotation-note">
            Same {money(r.value)} in {r.candidates.length} best pools of this
            profile. Fees are the lower of the 24 h and 7 d average after your
            dilution; IL is a σ²/8 estimate. Switch cost {money(r.cost)} covers
            exit, swaps and re-entry. The ranking is per dollar, so several
            positions can point at the same pool — read the note above the list
            before moving all of them.
          </p>
        </div>
      )}
    </div>
  );
}
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
type Owner = {
  address: string;
  name: string;
  tvl: number;
  pnl: number;
  roi: number;
  vaults: number;
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
  const [boardView, setBoardView] = useState("vaults");
  const [review, setReview] = useState<Evaluation | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const generation = useRef(0);
  const path =
    demo || (kind === "positions" && !settings.wallet)
      ? null
      : `/api/market/${kind}?${new URLSearchParams({
          chain: String(settings.chain),
          ...(kind === "positions" ? { wallet: settings.wallet } : {}),
        })}`;
  const resource = useResource<{
    rows: Vault[] | RankedVault[];
    owners?: Owner[];
    fetchedAt: number;
  }>(
    path,
    kind === "positions"
      ? { ttl: 60, interval: 60 }
      : { ttl: 300, interval: 300 },
  );
  const vaults = (
    kind === "positions" ? (resource.data?.rows ?? []) : []
  ) as Vault[];
  const rotations = useResource<{ rows: RotationRow[]; fetchedAt: number }>(
    kind === "positions" && path
      ? `/api/market/rotations?${new URLSearchParams({
          chain: String(settings.chain),
          wallet: settings.wallet,
          source: settings.source,
          profile: settings.profile,
          quote: defaultQuote(settings.chain),
        })}`
      : null,
    { ttl: 60, interval: 60 },
  );
  const rotationById = new Map(
    (rotations.data?.rows ?? []).map((r) => [r.id, r] as const),
  );
  // Several ROTATE verdicts on one pool: the per-dollar ranking does not see the portfolio.
  const concentration = (() => {
    const rows = (rotations.data?.rows ?? []).filter(
      (r) => r.kind === "rotate" && r.best,
    );
    const byPool = new Map<
      string,
      { pair: string; tvl: number; value: number; n: number }
    >();
    for (const r of rows) {
      const b = r.best!;
      const cur = byPool.get(b.poolId) ?? {
        pair: b.pair,
        tvl: b.tvl,
        value: 0,
        n: 0,
      };
      cur.value += r.value;
      cur.n += 1;
      byPool.set(b.poolId, cur);
    }
    const top = [...byPool.values()].sort((a, b) => b.n - a.n)[0];
    if (!top || top.n < 2) return null;
    return { ...top, share: top.value / (top.tvl + top.value) };
  })();
  const [openRotation, setOpenRotation] = useState<string | null>(null);
  const ranked = (
    kind === "leaderboard" ? (resource.data?.rows ?? []) : []
  ) as RankedVault[];
  const owners: Owner[] = useMemo(
    () => resource.data?.owners ?? [],
    [resource.data],
  );
  const ownerPaging = usePagination(owners, `${kind}:${settings.chain}`);
  const rankedPaging = usePagination(ranked, `${kind}:${settings.chain}`);
  const busy = resource.busy;
  const error = resource.error || reviewError;
  const time = resource.fetchedAt;
  const boardNote = time
    ? `Fetched ${new Date(time * 1000).toLocaleTimeString()} · refreshes every 5 min`
    : "Awaiting source";
  useEffect(() => {
    generation.current++;
    setReview(null);
    setReviewBusy(false);
    setReviewError("");
  }, [path]);
  useEffect(() => {
    if (refresh && path) {
      resource.refresh();
      rotations.refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh]);
  async function inspect(v: Vault) {
    const id = generation.current;
    setReviewBusy(true);
    setReview(null);
    setReviewError("");
    try {
      const data = await request(
        `/api/market/review?chain=${v.chain_id}&address=${encodeURIComponent(v.address)}`,
      );
      if (id === generation.current) setReview(data.evaluation);
    } catch (e) {
      if (id === generation.current)
        setReviewError(e instanceof Error ? e.message : "Review unavailable.");
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
      {kind === "positions" && vaults.length > 0 && (
        <details className="record-details">
          <summary>
            <span className="eyebrow">Track record</span> how Curator&apos;s
            verdicts have held up, all users, last 30 days
          </summary>
          <TrackRecord compact />
        </details>
      )}
      {kind === "positions" && concentration && (
        <p className="notice concentration" role="note">
          <strong>
            {concentration.n} verdicts point at {concentration.pair}.
          </strong>{" "}
          The ranking is per dollar, not per portfolio: moving all of them puts{" "}
          {money(concentration.value)} into one pool
          {concentration.share >= 0.05
            ? ` — ${(concentration.share * 100).toFixed(1)}% of its liquidity after you enter, which the fee estimate does not survive.`
            : ` (${(concentration.share * 100).toFixed(1)}% of its liquidity). Rotate one, watch a day, then decide on the next.`}
        </p>
      )}
      {kind === "positions" ? (
        vaults.map((v) => (
          <article key={v.address} className="vault-card">
            <header>
              <h2>
                {v.name}
                <AddressChip
                  address={v.address}
                  chain={v.chain_id}
                  kind="vault"
                  label={`${v.name} · vault`}
                  krystalUrl={v.url}
                  className="inline"
                />
              </h2>
              <a
                className="text-link"
                href={withRef(v.url)}
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
            {v.positions.length > 0 && (
              <div className="position-head" aria-hidden="true">
                <span>Position</span>
                <span>Range · price</span>
                <span>Value</span>
                <span>PnL</span>
                <span>Fees</span>
              </div>
            )}
            {v.positions.map((p) => {
              const inRange = p.status === "IN_RANGE";
              const age = ageLabel(p.opened_ts);
              return (
                <div className="position-row" key={p.id}>
                  <div className="position-id">
                    <PairMark
                      pool={{
                        pair: `${p.token0}/${p.token1}`,
                        token0: p.token0,
                        token1: p.token1,
                        protocol: "",
                      }}
                      showMeta={false}
                    />
                    <span className="position-meta">
                      <span className={`status-pill ${inRange ? "in" : "out"}`}>
                        {inRange ? "In range" : "Out of range"}
                      </span>
                      {p.protocol && <span>{protocolLabel(p.protocol)}</span>}
                      {age && <span>{age}</span>}
                      <AddressChip
                        address={p.pool_address}
                        chain={v.chain_id}
                        kind="pool"
                        label={`${p.token0}/${p.token1} · pool`}
                        className="tiny"
                      />
                    </span>
                  </div>
                  <RangeBar p={p} />
                  <div className="position-stat">
                    <strong>{money(p.value)}</strong>
                    <small>Deposited {money(p.deposit)}</small>
                  </div>
                  <div className="position-stat">
                    <strong className={p.pnl >= 0 ? "positive" : "amber"}>
                      {signed(p.pnl)}
                    </strong>
                    <small>
                      {p.roi_pct > 0 ? "+" : ""}
                      {p.roi_pct.toFixed(2)}% ROI
                      {p.il ? ` · IL ${money(p.il)}` : ""}
                    </small>
                  </div>
                  <div className="position-stat">
                    <strong>{money(p.fee_pending)}</strong>
                    <small>
                      Claimed {money(p.fee_claimed)}
                      {p.fee_apr ? ` · ${p.fee_apr.toFixed(1)}% APR` : ""}
                    </small>
                  </div>
                  {(() => {
                    const r = rotationById.get(p.id);
                    if (r)
                      return (
                        <RotationVerdict
                          r={r}
                          open={openRotation === p.id}
                          toggle={() =>
                            setOpenRotation(openRotation === p.id ? null : p.id)
                          }
                        />
                      );
                    if (rotations.busy && inRange)
                      return (
                        <div className="rotation rotation-pending">
                          Weighing alternatives…
                        </div>
                      );
                    return null;
                  })()}
                </div>
              );
            })}
          </article>
        ))
      ) : boardView === "owners" ? (
        <div className="data-panel">
          <div
            className="table-scroll standard"
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
                {ownerPaging.rows.map((o) => (
                  <tr key={o.address}>
                    <td>
                      <strong>{o.name}</strong>
                      <AddressChip
                        address={o.address}
                        chain={settings.chain}
                        kind="wallet"
                        label={`${o.name} · owner`}
                        className="tiny"
                      />
                    </td>
                    <td>{o.vaults}</td>
                    <td>{money(o.tvl, true)}</td>
                    <td>{money(o.pnl)}</td>
                    <td>{pct(o.roi)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!owners.length && !busy && (
            <div className="empty">No owners meet the ranking criteria.</div>
          )}
          <Pager paging={ownerPaging} unit="owners" note={boardNote} />
        </div>
      ) : (
        <div className="data-panel">
          <div
            className="table-scroll standard"
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
                {rankedPaging.rows.map((r) => (
                  <tr key={r.vault.address}>
                    <td>
                      <strong>{r.vault.name}</strong>
                      <AddressChip
                        address={r.vault.address}
                        chain={r.vault.chain_id}
                        kind="vault"
                        label={`${r.vault.name} · vault`}
                        krystalUrl={r.url}
                        className="tiny"
                      />
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
                        title="Rule-based review: performance, instructions and risk checks against your limits → avoid / watch / worth testing"
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
          <Pager paging={rankedPaging} unit="vaults" note={boardNote} />
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
      {time && kind === "positions" && (
        <p className="fine-print">
          Fetched {new Date(time * 1000).toLocaleString()} · refreshes every 60s
        </p>
      )}
    </div>
  );
}
