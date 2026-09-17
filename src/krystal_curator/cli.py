"""Entry point. `krystal-curator` opens the TUI; `krystal-curator scan` prints a table."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich import box
from rich.console import Console
from rich.table import Table

from . import api, leaderboard, net, notify
from .config import Config
from .config import load as load_config
from .env import load_dotenv
from .position import simulate
from .profiles import PROFILE_ORDER, PROFILES

if TYPE_CHECKING:
    from .store import Store


def _common(ap: argparse.ArgumentParser, cfg: Config) -> None:
    """Shared flags; defaults come from config.toml / env so flags only override."""
    ap.add_argument("--chain", type=int, default=cfg.chain, help=f"chainId (default {cfg.chain})")
    ap.add_argument(
        "--source",
        choices=api.SOURCES,
        default=cfg.pool_source,
        help=f"pool feed: krystal (any chain) or rhpools (chain-indexed, Robinhood only) "
        f"(default {cfg.pool_source})",
    )
    ap.add_argument(
        "--rhpools-url",
        default=cfg.rhpools_url,
        help=f"robinhoodpools base URL for --source rhpools (default {cfg.rhpools_url})",
    )
    ap.set_defaults(rhpools_top=cfg.rhpools_top, rhpools_windows=list(cfg.rhpools_windows))
    ap.add_argument(
        "--reconcile",
        action=argparse.BooleanOptionalAction,
        default=cfg.reconcile,
        help="also fetch the other feed and show SRCΔ, its TVL/volume disagreement "
        f"(Robinhood only; default {cfg.reconcile})",
    )
    ap.add_argument(
        "--profile",
        choices=PROFILE_ORDER,
        default=cfg.profile,
        help=f"risk profile (default {cfg.profile})",
    )
    ap.add_argument(
        "--quote",
        default=cfg.quote,
        help=f"only pools containing this token; 'any' disables (default {cfg.quote})",
    )
    ap.add_argument(
        "--protocol",
        action="append",
        default=None,
        help="restrict to protocol key(s); repeatable"
        + (f" (default {cfg.protocols})" if cfg.protocols else ""),
    )
    ap.add_argument(
        "--size",
        type=float,
        default=cfg.size,
        help=f"your position size in USD (default {cfg.size:,.0f})",
    )
    ap.add_argument(
        "--wallet",
        default=cfg.wallet or None,
        help=f"wallet for positions + monitoring (default from config / ${api.WALLET_ENV})",
    )


def build_parser(cfg: Config) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="krystal-curator", description="Krystal LP pool screener")
    ap.add_argument("--config", default=None, help="path to config.toml (default: auto-discover)")
    sub = ap.add_subparsers(dest="cmd")

    tui = sub.add_parser("tui", help="interactive terminal (default)")
    _common(tui, cfg)
    tui.add_argument(
        "--refresh",
        type=int,
        default=cfg.refresh,
        help=f"auto-refresh every N seconds (0 = off, default {cfg.refresh})",
    )
    tui.add_argument(
        "--images",
        choices=["auto", "tgp", "sixel", "halfcell", "unicode", "off"],
        default=cfg.images or None,
        help="logo renderer; default auto (Kitty/Sixel graphics), halfcell on Warp.",
    )

    scan = sub.add_parser("scan", help="print ranked table, optional CSV")
    _common(scan, cfg)
    scan.add_argument("--top", type=int, default=25)
    scan.add_argument("--csv", type=Path, default=None)
    scan.add_argument(
        "--tx",
        action="store_true",
        help=f"fetch 24h tx count for the top rows via Cloud API (needs ${api.CLOUD_KEY_ENV}; costs credits)",
    )
    watch = sub.add_parser("watch", help="headless monitor loop: snapshots + alerts (Telegram)")
    _common(watch, cfg)
    watch.add_argument(
        "--interval",
        type=int,
        default=cfg.interval,
        help=f"seconds between ticks (default {cfg.interval})",
    )
    watch.add_argument(
        "--telegram",
        action=argparse.BooleanOptionalAction,
        default=cfg.telegram,
        help=f"send alerts via Telegram (needs ${notify.TOKEN_ENV} and ${notify.CHAT_ENV})",
    )
    watch.add_argument(
        "--digest-hour",
        type=int,
        default=cfg.digest_hour,
        help="UTC hour to write (and send) the daily vault report, e.g. 0",
    )
    watch.add_argument("--once", action="store_true", help="one tick then exit (cron mode)")

    bt = sub.add_parser(
        "backtest", help="does the score predict forward fee yield? (local history)"
    )
    _common(bt, cfg)
    bt.add_argument(
        "--horizon", type=float, default=24, help="hours ahead to evaluate (default 24)"
    )
    bt.add_argument("--days", type=float, default=14, help="history window in days (default 14)")
    bt.add_argument(
        "--sigma",
        action="store_true",
        help="only check whether the feed's priceVolatility is a daily σ (realised vs reported)",
    )

    setup = sub.add_parser(
        "setup", help="Krystal Automation values to enter for each open position"
    )
    _common(setup, cfg)

    vr = sub.add_parser(
        "vault-review",
        help="review one public AutoFarm vault from its URL: settings, positions, plans, report",
    )
    vr.add_argument(
        "url", help="https://defi.krystal.app/vaults/<chain>/<address> or <chain>/<address>"
    )
    vr.add_argument(
        "--out", type=Path, default=Path("reports"), help="report directory (default reports/)"
    )
    vr.add_argument(
        "--plans", type=int, default=100, help="newest action plans to analyse (default 100)"
    )
    vr.add_argument(
        "--no-raw", action="store_true", help="omit verbatim API responses from the JSON"
    )
    vr.add_argument("--quiet", action="store_true", help="only print the written paths")

    lb = sub.add_parser(
        "vault-leaderboard",
        help="every public AutoFarm vault on the chain: who earns on their capital, "
        "which vaults are copy candidates, optionally reviewed",
    )
    lb.add_argument("--chain", type=int, default=cfg.chain, help=f"chainId (default {cfg.chain})")
    lb.add_argument("--top", type=int, default=20, help="rows per table (default 20)")
    lb.add_argument(
        "--sort",
        choices=leaderboard.SORTS,
        default="roi",
        help="roi = annualised pnl / deposited, pnl = $, apr = feed fee APR, "
        "30d = earning30d / tvl (default roi)",
    )
    lb.add_argument(
        "--min-tvl",
        type=float,
        default=leaderboard.MIN_TVL,
        help=f"candidate floor on TVL (default {leaderboard.MIN_TVL:,.0f})",
    )
    lb.add_argument(
        "--min-age",
        type=float,
        default=None,
        help="candidate floor on age in days (default: the evaluation's evidence floor)",
    )
    lb.add_argument(
        "--review",
        type=int,
        default=0,
        metavar="N",
        help="run the full vault-review evaluation on the top N candidates (≈5 requests each)",
    )
    lb.add_argument(
        "--write",
        action="store_true",
        help="with --review: also write each reviewed vault's report to --out",
    )
    lb.add_argument(
        "--out", type=Path, default=Path("reports"), help="report directory (default reports/)"
    )

    init = sub.add_parser("init", help="write config.toml and .env templates here")
    init.add_argument("--force", action="store_true", help="overwrite existing files")
    sub.add_parser("config", help="show the effective configuration and where it came from")
    sub.add_parser("status", help="daemon heartbeat, db size, last alerts")
    return ap


def _recon_cell(r) -> str:
    """SRCΔ for the scan table: TVL delta vs the other feed, coloured by severity."""
    if r is None:
        return "[dim]-[/dim]"
    color = {"warn": "red", "note": "yellow", "ok": "green"}.get(r.level, "dim")
    return f"[{color}]{r.headline}[/{color}]"


def _pool_kwargs(args: argparse.Namespace) -> dict:
    """Feed selection for api.fetch_pools from the shared flags."""
    return {
        "source": args.source,
        "rhpools_url": args.rhpools_url,
        "rhpools_top": args.rhpools_top,
        "rhpools_windows": args.rhpools_windows,
    }


def run_setup(args: argparse.Namespace) -> int:
    from .autoconfig import recommend
    from .monitor import Monitor
    from .store import Store
    from .vaults import fetch_vaults

    con = Console(width=None if sys.stdout.isatty() else 150)
    wallet = args.wallet or api.wallet()
    if not wallet:
        con.print(f"[red]need a wallet: --wallet or {api.WALLET_ENV}[/red]")
        return 2
    try:
        pools = api.fetch_pools(args.chain, **_pool_kwargs(args))
        vaults = fetch_vaults(wallet, chain_id=args.chain)
    except api.KrystalError as e:
        con.print(f"[red]{e}[/red]")
        return 2
    mon = Monitor(Store(), profile=PROFILES[args.profile], pools=pools, vaults=vaults)
    opens = mon.open_positions()
    if not opens:
        con.print("[yellow]no open positions[/yellow]")
        return 1
    for p in opens:
        su = recommend(p, mon.sigma_for(p), PROFILES[args.profile])
        con.rule(
            f"[bold #ffb000]{p.vault or 'wallet'}  {p.pair}  [{p.protocol}]  {p.value:,.0f}$  "
            f"range {p.min_price:,.4g}–{p.max_price:,.4g}  now {p.current_price or 0:,.4g}"
        )
        t = Table(box=box.SIMPLE_HEAD, header_style="bold #ffb000", pad_edge=False)
        t.add_column("SECTION", style="#ffb000")
        t.add_column("FIELD", style="bold")
        t.add_column("VALUE")
        t.add_column("WHY", style="dim")
        for section, fs in su.by_section().items():
            for i, f in enumerate(fs):
                t.add_row(section if i == 0 else "", f.label, f.value, f.why)
        con.print(t)
    con.print(
        f"[dim]profile {args.profile}: ±σ·√{ {'conservative': 14, 'balanced': 7, 'aggressive': 3, 'degen': 1}[args.profile] }d range; "
        "rerun with --profile to change the risk stance[/dim]"
    )
    return 0


def run_init(args: argparse.Namespace) -> int:
    from .config import write_templates

    con = Console()
    made = write_templates(Path.cwd(), force=args.force)
    if not made:
        con.print("[yellow]config.toml and .env already exist (use --force to overwrite)[/yellow]")
        return 1
    for p in made:
        con.print(f"wrote [bold]{p.name}[/bold]")
    con.print(
        "edit them, then: [bold]uv run krystal-curator[/bold]  or  [bold]uv run krystal-curator watch[/bold]"
    )
    return 0


def run_config(cfg: Config) -> int:
    from dataclasses import fields

    from .config import data_dir

    con = Console()
    con.print(
        f"[bold #ffb000]config[/]: {cfg.source or 'built-in defaults (no config.toml found)'}"
    )
    con.print(f"[bold #ffb000]data dir[/]: {data_dir()}")
    t = Table(box=box.SIMPLE_HEAD, header_style="bold #ffb000", pad_edge=False)
    t.add_column("KEY")
    t.add_column("VALUE")
    for f in fields(Config):
        if f.name in ("source", "alerts"):
            continue
        v = getattr(cfg, f.name)
        if f.name == "wallet" and v:
            v = f"{v[:6]}…{v[-4:]}"
        t.add_row(f.name, str(v))
    for f in fields(cfg.alerts):
        t.add_row(f"alerts.{f.name}", str(getattr(cfg.alerts, f.name)))
    con.print(t)
    have = {
        "KRYSTAL_CLOUD_KEY": bool(api.cloud_key()),
        "TELEGRAM_BOT_TOKEN": bool(__import__("os").environ.get(notify.TOKEN_ENV)),
        "TELEGRAM_CHAT_ID": bool(__import__("os").environ.get(notify.CHAT_ENV)),
    }
    con.print(
        "secrets: "
        + "   ".join(
            f"{k} {'[green]set[/green]' if v else '[dim]unset[/dim]'}" for k, v in have.items()
        )
    )
    return 0


def run_status() -> int:
    import time

    from .config import data_dir
    from .store import Store, default_db

    con = Console()
    db = default_db()
    if not db.exists():
        con.print(f"[yellow]no database yet at {db}[/yellow]")
        return 1
    st = Store(db)
    hb = st.kv_get("watch.heartbeat") or {}
    size_mb = db.stat().st_size / 1e6
    con.print(
        f"[bold #ffb000]db[/]: {db} ({size_mb:.1f} MB)   [bold #ffb000]data dir[/]: {data_dir()}"
    )
    if hb:
        age = time.time() - float(hb.get("ts", 0))
        stale = age > 3 * float(hb.get("interval", 300))
        con.print(
            f"[bold #ffb000]watch[/]: last tick {age / 60:.1f} min ago "
            + ("[red](STALE)[/red]" if stale else "[green](alive)[/green]")
            + f"   pools {hb.get('pools')}   vaults {hb.get('vaults')}   open {hb.get('open')} "
            f"(OOR {hb.get('oor')})   ticks {hb.get('ticks')}   telegram {hb.get('telegram')}"
        )
        last = st.kv_get("watch.last_alerts") or []
        if last:
            con.print("[bold #ffb000]last alerts[/]:")
            for a in last[-10:]:
                con.print(f"  {a.get('when', '')}  {a.get('title')}: {a.get('text')}")
    else:
        con.print("[dim]no daemon heartbeat recorded (run `krystal-curator watch`)[/dim]")
    with st._lock:
        n_snap = st._db.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM snapshots").fetchone()
        n_vault = st._db.execute("SELECT COUNT(*) FROM vault_snapshots").fetchone()[0]
        n_seen = st._db.execute("SELECT COUNT(*) FROM pools_seen").fetchone()[0]
        n_watch = st._db.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    span = (n_snap[2] - n_snap[1]) / 3600 if n_snap[1] else 0
    con.print(
        f"[bold #ffb000]history[/]: {n_snap[0]:,} pool snapshots over {span:.0f}h   "
        f"{n_vault} vault snapshots   {n_seen} pools seen   {n_watch} starred"
    )
    return 0


def run_sigma_check(args: argparse.Namespace, store: Store, con: Console) -> int:
    from .backtest import SIGMA_MIN_RETURNS, SIGMA_MIN_SPAN_H, sigma_check

    chk = sigma_check(store.price_series(args.chain, args.days))
    con.print(
        f"[bold #ffb000]priceVolatility check[/]: {len(chk.rows)} pools with ≥{SIGMA_MIN_RETURNS} "
        f"priced returns over ≥{SIGMA_MIN_SPAN_H:.0f}h ({chk.skipped} skipped)"
    )
    if not chk.rows:
        con.print(
            "[yellow]no priced history yet — snapshots record a price since this version; "
            "run the TUI or `watch` for a day first[/yellow]"
        )
        return 1
    t = Table(header_style="bold #ffb000", box=box.SIMPLE_HEAD, pad_edge=False)
    for c in ("POOL", "N", "SPAN", "STALE", "REALISED σ/d", "REPORTED", "RATIO"):
        t.add_column(c, justify="left" if c == "POOL" else "right")
    for r in chk.rows[:40]:
        t.add_row(
            r.key[:24],
            str(r.n),
            f"{r.span_h:.0f}h",
            f"{r.stale_frac * 100:.0f}%",
            f"{r.realised:.2f}%",
            f"{r.reported:.2f}%",
            "-" if r.ratio is None else f"{r.ratio:.2f}",
        )
    con.print(t)
    con.print(f"[bold]{chk.verdict}[/bold]")
    con.print(
        "[dim]ratio ≈ 1 ⇒ daily σ (current assumption); ≈ 0.38 ⇒ 7-day; ≈ 0.18 ⇒ 30-day; "
        "≈ 0.05 ⇒ annualised. High STALE means the feed price did not move between "
        "snapshots, which pulls realised σ down.[/dim]"
    )
    return 0


def run_backtest(args: argparse.Namespace) -> int:
    from .backtest import evaluate, il_check
    from .profiles import PROFILE_ORDER
    from .store import Store

    con = Console(width=None if sys.stdout.isatty() else 140)
    store = Store()
    if args.sigma:
        return run_sigma_check(args, store, con)
    rows = [r for r in store.all_snapshots(args.days) if r[1] == args.chain]
    times = len({r[0] for r in rows})
    con.print(
        f"[bold #ffb000]local history[/]: {len(rows):,} pool snapshots over {times} refresh times"
    )
    if times < 2:
        con.print(
            "[yellow]need snapshots ≥ horizon apart — run the TUI or `watch` for a day first[/yellow]"
        )
        return 1
    t = Table(header_style="bold #ffb000", box=box.SIMPLE_HEAD, pad_edge=False)
    for c in (
        "PROFILE",
        "PAIRS",
        "TIMES",
        "SPEARMAN",
        "TOP DECILE %/d",
        "BOTTOM %/d",
        "STEADY",
        "FADING",
        "SPIKE",
    ):
        t.add_column(c, justify="right" if c != "PROFILE" else "left")
    comps: dict[str, dict[str, float]] = {}
    for key in PROFILE_ORDER:
        r = evaluate(rows, PROFILES[key], horizon_h=args.horizon)
        comps[key] = r.component_spearman
        pct = lambda v: "-" if v is None else f"{v * 100:.3f}"
        t.add_row(
            key,
            str(r.pairs),
            str(r.times),
            "-" if r.spearman is None else f"{r.spearman:+.2f}",
            pct(r.decile_yield[0] if r.decile_yield else None),
            pct(r.decile_yield[-1] if r.decile_yield else None),
            pct(r.steady_next_yield),
            pct(r.fading_next_yield),
            pct(r.spike_next_yield),
        )
    con.print(t)
    con.print(
        "[dim]spearman: rank correlation between score at T and fee yield at T+horizon; "
        "+1 perfect, 0 none. Top vs bottom decile is the practical gap.[/dim]"
    )
    c = Table(
        title="component → forward yield (spearman)",
        header_style="bold #ffb000",
        box=box.SIMPLE_HEAD,
        pad_edge=False,
    )
    c.add_column("PROFILE")
    names = ["yield", "turnover", "consistency", "liveness", "depth", "risk"]
    for n in names:
        c.add_column(n, justify="right")
    for key, cs in comps.items():
        c.add_row(key, *[f"{cs.get(n, 0.0):+.2f}" if cs else "-" for n in names])
    con.print(c)

    wallet = args.wallet or api.wallet()
    if wallet:
        from .vaults import fetch_vaults

        try:
            vaults = fetch_vaults(wallet, chain_id=args.chain)
            pools = api.fetch_pools(args.chain, **_pool_kwargs(args))
        except api.KrystalError as e:
            con.print(f"[red]{e}[/red]")
            return 0
        sig = {p.address: p.volatility for p in pools}
        closed = [p for v in vaults for p in v.closed]
        chk = il_check(closed, sig)
        con.print(
            f"\n[bold #ffb000]IL model vs your closed trades[/] ({chk.n} with a known pool σ)"
        )
        if chk.n:
            con.print(
                f"  predicted IL (σ²/8·days·deposit): [red]-{chk.predicted_il:,.1f}$[/red]   "
                f"realised price PnL: {chk.realised_price_pnl:+,.1f}$   fees: +{chk.fees:,.1f}$"
            )
            con.print(
                "  [dim]price PnL more negative than predicted ⇒ model under-estimates IL for your "
                "ranges (concentrated); less negative ⇒ conservative.[/dim]"
            )
    return 0


def run_scan(args: argparse.Namespace) -> int:
    from .scoring import curate
    from .tui import write_csv

    con = Console(width=None if sys.stdout.isatty() else 180)
    prof = PROFILES[args.profile]
    quote = None if args.quote.lower() == "any" else args.quote
    protos = set(args.protocol) or None
    try:
        pools = api.fetch_pools(args.chain, **_pool_kwargs(args))
    except api.KrystalError as e:
        con.print(f"[red]{e}[/red]")
        return 2
    from .risk import fill_realised_risk
    from .store import Store

    fill_realised_risk(pools, Store())  # σ / drawdown from TUI / daemon history, if any
    recon = None
    if args.reconcile:
        from .reconcile import reconcile

        try:
            other = api.fetch_reference_pools(args.chain, **_pool_kwargs(args))
        except api.KrystalError as e:
            con.print(f"[yellow]reconcile skipped: {e}[/yellow]")
            other = None
        if other is None:
            con.print("[yellow]reconcile: no second feed for this chain[/yellow]")
        else:
            recon = reconcile(pools, other)
            con.print(f"[dim]{recon.summary()}[/dim]")
    rows = curate(pools, prof, quote=quote, protocols=protos, recon=recon)[: args.top]
    from .enrich import FlowCache

    flows = FlowCache().fetch(args.chain, [s.pool.address for s in rows]) if rows else {}
    for s in rows:
        s.sim = simulate(s.pool, args.size)
        s.flow = flows.get(s.pool.address)
    if not rows:
        con.print("[red]no pool passes this profile; try --profile aggressive or --quote any[/red]")
        return 1

    if args.tx:
        key = api.cloud_key()
        if not key:
            con.print(f"[yellow]--tx ignored: ${api.CLOUD_KEY_ENV} not set[/yellow]")
        else:
            for s in rows:
                s.pool.tx24 = api.fetch_tx_count_24h(s.pool, key)

    t = Table(
        title=(
            f"{prof.name}  chain {args.chain}  quote {quote or 'any'}  "
            f"size ${args.size:,.0f}  {len(pools)} → {len(rows)}"
        ),
        header_style="bold #ffb000",
        border_style="#a05e00",
        box=box.SIMPLE_HEAD,
        pad_edge=False,
    )
    for c in (
        "#",
        "PAIR",
        "PROTO",
        "TIER%",
        "TVL",
        "VOL24",
        "FEE24",
        "Y24%",
        "Y7D%",
        "V/TVL",
        "CONS",
        "TX1H",
        "TX24",
        "σ%",
        "DD24",
        *(("SRCΔ",) if recon else ()),
        "MY$/D",
        "NET$/D",
        "SHARE",
        "SCORE",
        "RK",
        "FLAGS",
    ):
        t.add_column(c, justify="right" if c not in ("PAIR", "PROTO", "FLAGS") else "left")
    if args.tx:
        t.add_column("TX24", justify="right")
    for i, s in enumerate(rows, 1):
        p = s.pool
        cells = [
            str(i),
            p.pair,
            p.protocol,
            f"{p.fee_tier_pct:.2f}",
            f"{p.tvl:,.0f}",
            f"{p.s24h.volume:,.0f}",
            f"{p.s24h.fee:,.0f}",
            f"{p.fee_yield_24h * 100:.2f}",
            f"{p.fee_yield_7d_daily * 100:.2f}",
            f"{p.turnover_24h:.1f}",
            f"{p.consistency:.2f}",
            f"{s.flow.tx_h1:,}" if s.flow and s.flow.tx_h24 else "-",
            f"{s.flow.tx_h24:,}" if s.flow and s.flow.tx_h24 else "-",
            f"{p.volatility:.1f}",
            f"{p.drawdown24h:.1f}",
            *((_recon_cell(s.recon),) if recon else ()),
            f"{s.sim.fee_day:,.0f}",
            f"{s.sim.net_day:+,.0f}",
            f"{s.sim.share * 100:.1f}%",
            f"{s.score:.1f}",
            s.grade,
            " ".join(s.flags),
        ]
        if args.tx:
            cells.append("-" if p.tx24 is None else f"{p.tx24:,}")
        t.add_row(*cells)
    con.print(t)
    con.print("[dim]URLs:[/dim]")
    for i, s in enumerate(rows, 1):
        con.print(f"[dim]{i:>3}[/dim] {s.pool.url}")

    if args.csv:
        write_csv(args.csv, rows)
        con.print(f"saved {args.csv}")
    return 0


def run_vault_review(args: argparse.Namespace) -> int:
    from rich.markdown import Markdown

    from . import vault_eval
    from . import vault_review as vr

    con = Console()
    try:
        chain_id, address = vr.parse_vault_url(args.url)
    except vr.VaultUrlError as e:
        con.print(f"[red]{e}[/red]")
        return 2
    try:
        rv = vr.fetch_review(chain_id, address, plans_limit=args.plans)
    except (api.KrystalError, net.HttpError) as e:
        con.print(f"[red]{net.redact(str(e))}[/red]")
        return 1
    ev = vault_eval.evaluate(rv)
    md, js = vr.write_review(rv, args.out, raw=not args.no_raw, evaluation=ev)
    if not args.quiet:
        con.print(Markdown(md.read_text(encoding="utf-8")))
    con.print(f"verdict: [bold]{ev.verdict}[/bold] — " + "; ".join(ev.reasons[:2]))
    con.print(f"wrote {md} and {js}")
    return 0


def run_vault_leaderboard(args: argparse.Namespace) -> int:
    from dataclasses import replace

    from . import vault_eval
    from . import vault_review as vr
    from .vaults import fetch_public_vaults

    con = Console(width=None if sys.stdout.isatty() else 170)
    try:
        vaults = fetch_public_vaults(args.chain)
    except (api.KrystalError, net.HttpError) as e:
        con.print(f"[red]{net.redact(str(e))}[/red]")
        return 1
    lim = vault_eval.DEFAULT_LIMITS
    if args.min_age is not None:
        lim = replace(lim, min_age_days=args.min_age)
    board = leaderboard.rank(vaults, sort=args.sort, lim=lim, min_tvl=args.min_tvl)
    if not board.vaults:
        con.print(f"[yellow]no public AutoFarm vault on chain {args.chain}[/yellow]")
        return 1

    o = Table(
        title=f"owners  chain {args.chain}  {len(board.owners)} owners of {board.total} vaults  "
        f"sort {args.sort}",
        header_style="bold #ffb000",
        border_style="#a05e00",
        box=box.SIMPLE_HEAD,
        pad_edge=False,
    )
    o.add_column("#", justify="right")
    for c in leaderboard.OWNER_COLUMNS:
        o.add_column(c, justify="left" if c in leaderboard.TEXT_COLUMNS else "right")
    for i, ow in enumerate(board.owners[: args.top], 1):
        o.add_row(str(i), *leaderboard.owner_cells(ow))
    con.print(o)
    con.print(
        f"[dim]ROI% = Σpnl / Σlifetime deposits (not annualised); owners keep their losers; "
        f"owners below {args.min_tvl:,.0f}$ deposited are not ranked[/dim]\n"
    )

    t = Table(
        title=f"vaults  {len(board.candidates)} copy candidates of {board.total}  "
        f"(age ≥ {lim.min_age_days:g}d, tvl ≥ {args.min_tvl:,.0f}, pnl > 0, tx costs ≤ "
        f"{leaderboard.MAX_COST_SHARE * 100:.0f}% of fees, agent on)",
        header_style="bold #ffb000",
        border_style="#a05e00",
        box=box.SIMPLE_HEAD,
        pad_edge=False,
    )
    t.add_column("#", justify="right")
    for c in leaderboard.VAULT_COLUMNS:
        t.add_column(c, justify="left" if c in leaderboard.TEXT_COLUMNS else "right")
    shown = board.vaults[: args.top]
    for i, r in enumerate(shown, 1):
        *cells, copy = leaderboard.vault_cells(r)
        t.add_row(str(i), *cells, "[green]yes[/green]" if r.candidate else f"[dim]{copy}[/dim]")
    con.print(t)
    con.print("[dim]URLs:[/dim]")
    for i, r in enumerate(shown, 1):
        con.print(f"[dim]{i:>3}[/dim] {r.vault.url}")

    if args.review <= 0:
        return 0
    picks = board.candidates[: args.review]
    if not picks:
        con.print("[yellow]no candidate to review; loosen --min-age / --min-tvl[/yellow]")
        return 1
    con.print(f"\n[bold #ffb000]review[/]: top {len(picks)} candidates")
    rt = Table(header_style="bold #ffb000", box=box.SIMPLE_HEAD, pad_edge=False)
    for c in ("VAULT", "VERDICT", "WHY"):
        rt.add_column(c)
    color = {"worth_testing": "green", "watch": "yellow", "avoid": "red"}
    for r in picks:
        v = r.vault
        try:
            rv = vr.fetch_review(v.chain_id, v.address)
        except (api.KrystalError, net.HttpError) as e:
            rt.add_row(v.name[:28], "[red]error[/red]", net.redact(str(e))[:80])
            continue
        ev = vault_eval.evaluate(rv)
        why = "; ".join(ev.reasons[:2])
        if args.write:
            md, _ = vr.write_review(rv, args.out, evaluation=ev)
            why += f"  [dim]{md}[/dim]"
        rt.add_row(v.name[:28], f"[{color.get(ev.verdict, 'dim')}]{ev.verdict}[/]", why)
    con.print(rt)
    return 0


def run_tui(args: argparse.Namespace, cfg: Config) -> int:
    from .tui import CuratorApp

    quote = None if args.quote.lower() == "any" else args.quote
    CuratorApp(
        chain_id=args.chain,
        profile=args.profile,
        quote=quote,
        protocols=set(args.protocol) or None,
        image_mode=args.images,
        size=args.size,
        refresh_seconds=args.refresh,
        wallet=args.wallet,
        config=cfg,
    ).run()
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    argv = list(sys.argv[1:] if argv is None else argv)
    # --config must be known before defaults are built
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None)
    pre_args, _ = pre.parse_known_args(argv)
    cfg = load_config(pre_args.config)
    ap = build_parser(cfg)
    args = ap.parse_args(argv)
    if getattr(args, "protocol", None) is None and hasattr(args, "protocol"):
        args.protocol = list(cfg.protocols)
    if hasattr(args, "source"):  # flags win over config for the TUI / daemon too
        cfg.pool_source = args.source
        cfg.rhpools_url = args.rhpools_url
        cfg.reconcile = args.reconcile
    if args.cmd == "init":
        return run_init(args)
    if args.cmd == "setup":
        return run_setup(args)
    if args.cmd == "config":
        return run_config(cfg)
    if args.cmd == "status":
        return run_status()
    if args.cmd == "scan":
        return run_scan(args)
    if args.cmd == "backtest":
        return run_backtest(args)
    if args.cmd == "vault-review":
        return run_vault_review(args)
    if args.cmd == "vault-leaderboard":
        return run_vault_leaderboard(args)
    if args.cmd == "watch":
        from .daemon import run_watch

        return run_watch(
            chain_id=args.chain,
            wallet=args.wallet or api.wallet(),
            interval=args.interval,
            profile=args.profile,
            telegram=args.telegram,
            digest_hour=args.digest_hour,
            once=args.once,
            config=cfg,
        )
    if args.cmd is None:
        args = ap.parse_args(["tui", *argv])
        if args.protocol is None:
            args.protocol = list(cfg.protocols)
    return run_tui(args, cfg)
