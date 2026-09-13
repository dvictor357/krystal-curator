"""Entry point. `krystal-curator` opens the TUI; `krystal-curator scan` prints a table."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table

from . import api, notify
from .env import load_dotenv
from .models import ROBINHOOD
from .position import simulate
from .profiles import PROFILE_ORDER, PROFILES


def _common(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--chain", type=int, default=ROBINHOOD, help="chainId (default Robinhood 4663)")
    ap.add_argument(
        "--profile",
        choices=PROFILE_ORDER,
        default="balanced",
        help="risk profile (default balanced)",
    )
    ap.add_argument(
        "--quote",
        default="USDG",
        help="only pools containing this token; 'any' disables (default USDG)",
    )
    ap.add_argument(
        "--protocol",
        action="append",
        default=[],
        help="restrict to protocol key(s); repeatable",
    )
    ap.add_argument(
        "--size", type=float, default=50_000, help="your position size in USD (default 50000)"
    )
    ap.add_argument(
        "--wallet",
        default=None,
        help=f"wallet for the positions view (or ${api.WALLET_ENV} / .env); needs ${api.CLOUD_KEY_ENV}",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="krystal-curator", description="Krystal LP pool screener")
    sub = ap.add_subparsers(dest="cmd")

    tui = sub.add_parser("tui", help="interactive terminal (default)")
    _common(tui)
    tui.add_argument(
        "--refresh",
        type=int,
        default=300,
        help="auto-refresh every N seconds (0 = off, default 300)",
    )
    tui.add_argument(
        "--images",
        choices=["auto", "tgp", "sixel", "halfcell", "unicode", "off"],
        default=None,
        help="logo renderer; default auto (Kitty/Sixel graphics), halfcell on Warp. "
        "Also via KRYSTAL_IMAGE env.",
    )

    scan = sub.add_parser("scan", help="print ranked table, optional CSV")
    _common(scan)
    scan.add_argument("--top", type=int, default=25)
    scan.add_argument("--csv", type=Path, default=None)
    scan.add_argument(
        "--tx",
        action="store_true",
        help=f"fetch 24h tx count for the top rows via Cloud API (needs ${api.CLOUD_KEY_ENV}; costs credits)",
    )
    watch = sub.add_parser("watch", help="headless monitor loop: snapshots + alerts (Telegram)")
    _common(watch)
    watch.add_argument(
        "--interval", type=int, default=300, help="seconds between ticks (default 300)"
    )
    watch.add_argument(
        "--telegram",
        action="store_true",
        help=f"send alerts via Telegram (needs ${notify.TOKEN_ENV} and ${notify.CHAT_ENV})",
    )
    watch.add_argument(
        "--digest-hour",
        type=int,
        default=None,
        help="UTC hour to write (and send) the daily vault report, e.g. 0",
    )
    watch.add_argument("--once", action="store_true", help="one tick then exit (cron mode)")

    bt = sub.add_parser(
        "backtest", help="does the score predict forward fee yield? (local history)"
    )
    _common(bt)
    bt.add_argument(
        "--horizon", type=float, default=24, help="hours ahead to evaluate (default 24)"
    )
    bt.add_argument("--days", type=float, default=14, help="history window in days (default 14)")
    return ap


def run_backtest(args: argparse.Namespace) -> int:
    from .backtest import evaluate, il_check
    from .profiles import PROFILE_ORDER
    from .store import Store

    con = Console(width=None if sys.stdout.isatty() else 140)
    store = Store()
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
            pools = api.fetch_pools(args.chain)
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
        pools = api.fetch_pools(args.chain)
    except api.KrystalError as e:
        con.print(f"[red]{e}[/red]")
        return 2
    rows = curate(pools, prof, quote=quote, protocols=protos)[: args.top]
    for s in rows:
        s.sim = simulate(s.pool, args.size)
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
        "σ%",
        "DD24",
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
            f"{p.volatility:.1f}",
            f"{p.drawdown24h:.1f}",
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


def run_tui(args: argparse.Namespace) -> int:
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
    ).run()
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.cmd == "scan":
        return run_scan(args)
    if args.cmd == "backtest":
        return run_backtest(args)
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
        )
    if args.cmd is None:
        args = ap.parse_args(["tui", *(argv or sys.argv[1:])])
    return run_tui(args)
