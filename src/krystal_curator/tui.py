"""Terminal UI. Bloomberg-ish: dense table, amber chrome, single-key commands."""

from __future__ import annotations

import csv
import math
import os
import warnings
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option
from textual_image.widget import HalfcellImage, Image, SixelImage, TGPImage, UnicodeImage

from . import api
from .advisor import Advice, advise, price_ladder
from .analytics import idle_capital, real_roi, report_markdown, track_record
from .api import KrystalError
from .autoconfig import recommend
from .config import Config
from .enrich import Flow, FlowCache, TokenInfo, TokenMeta
from .models import Pool
from .monitor import Monitor
from .position import simulate
from .positions import POSITIONS_UNITS, Position, fetch_positions
from .profiles import PROFILES, RiskProfile
from .radar import render_radar
from .rotation import Rotation, plan
from .scoring import Scored, curate, score_pool
from .store import Delta, Store, sparkline
from .vaults import Vault, fetch_vaults

# textual-image renders palette PNGs fine; PIL just complains about the conversion.
warnings.filterwarnings("ignore", message="Palette images with Transparency", module="PIL")

IMAGE_MODES: dict[str, type[Widget] | None] = {
    "auto": Image,
    "tgp": TGPImage,
    "sixel": SixelImage,
    "halfcell": HalfcellImage,
    "unicode": UnicodeImage,
    "off": None,
}


def pick_image_mode(explicit: str | None = None) -> str:
    """CLI flag > KRYSTAL_IMAGE env > terminal heuristics."""
    mode = explicit or os.environ.get("KRYSTAL_IMAGE") or ""
    if mode in IMAGE_MODES:
        return mode
    # Warp prints graphics escapes as garbage; it does render coloured half blocks.
    if os.environ.get("TERM_PROGRAM") == "WarpTerminal":
        return "halfcell"
    return "auto"


RADAR_LABEL = {
    "yield": "YLD",
    "turnover": "TURN",
    "consistency": "CONS",
    "liveness": "LIVE",
    "depth": "DEPTH",
    "risk": "RISK",
}

COLUMNS = (
    "#",
    "★",
    "PAIR",
    "PROTO",
    "TIER%",
    "TVL",
    "VOL24",
    "FEE24",
    "ΔFEE",
    "TREND",
    "FEE/D 7D",
    "Y24%",
    "Y7D%",
    "V/TVL",
    "CONS",
    "LIVE",
    "TX1H",
    "TX24",
    "σ%",
    "DD24",
    "MY$/D",
    "NET$/D",
    "SHARE",
    "SCORE",
    "RK",
    "AGE",
    "LINKS",
    "FLAGS",
)


def _usd(x: float) -> str:
    if x >= 1e9:
        return f"{x / 1e9:.2f}B"
    if x >= 1e6:
        return f"{x / 1e6:.2f}M"
    if x >= 1e3:
        return f"{x / 1e3:.1f}K"
    return f"{x:.0f}"


def _pct(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}"


def _color_num(s: str, v: float, good_hi: float, bad_lo: float, *, invert: bool = False) -> Text:
    """Green above good_hi, red below bad_lo, grey between. invert swaps polarity."""
    hi, lo = (v <= bad_lo, v >= good_hi) if invert else (v >= good_hi, v <= bad_lo)
    style = "bold green" if hi else "bold red" if lo else ""
    return Text(s, style=style, justify="right")


def _tx_cell(f: Flow | None, win: str) -> Text:
    if f is None:
        return Text("…", style="dim", justify="right")
    n = f.tx_h1 if win == "h1" else f.tx_h24
    if f.tx_h24 == 0:
        return Text("-", style="dim", justify="right")
    style = ""
    if win == "h1":
        style = "bold green" if f.pace >= 1.5 else "red" if f.pace < 0.3 else ""
    elif n >= 5000:
        style = "bold green"
    elif n < 200:
        style = "red"
    return Text(f"{n:,}", style=style, justify="right")


def _age_text(p: Pool) -> Text:
    """Days since this tool first saw the pool (lower bound on its real age)."""
    d = p.seen_days
    if p.is_new:
        return Text("<1d", style="bold red", justify="right")
    if d is None:
        return Text("·", style="dim", justify="right")
    style = "red" if d < 1 else "yellow" if d < 3 else ""
    return Text(f"{d:.0f}d+" if d >= 1 else f"{d * 24:.0f}h+", style=style, justify="right")


def _days(d: float | None) -> str:
    if d is None:
        return "-"
    return "<0.1d" if d < 0.1 else f"{d:.1f}d"


def _delta_text(pct: float | None) -> Text:
    if pct is None:
        return Text("·", style="dim", justify="right")
    style = "bold green" if pct >= 10 else "bold red" if pct <= -10 else ""
    return Text(f"{pct:+.0f}%", style=style, justify="right")


def _grade_text(g: str) -> Text:
    colors = {
        "A": "green",
        "B": "bright_green",
        "C": "yellow",
        "D": "dark_orange",
        "E": "red",
    }
    return Text(g, style=f"bold {colors.get(g, 'white')}", justify="center")


# column label -> sort key. Columns missing here are not sortable.
SORTABLE: dict[str, Callable[[Scored], float | str]] = {
    "PAIR": lambda s: s.pool.pair,
    "PROTO": lambda s: s.pool.protocol,
    "TIER%": lambda s: s.pool.fee_tier_pct,
    "TVL": lambda s: s.pool.tvl,
    "VOL24": lambda s: s.pool.s24h.volume,
    "FEE24": lambda s: s.pool.s24h.fee,
    "ΔFEE": lambda s: s.delta.fee24_pct if s.delta and s.delta.fee24_pct is not None else -1e9,
    "★": lambda s: s.watched,
    "FEE/D 7D": lambda s: s.pool.s7d.fee / 7,
    "Y24%": lambda s: s.pool.fee_yield_24h,
    "Y7D%": lambda s: s.pool.fee_yield_7d_daily,
    "V/TVL": lambda s: s.pool.turnover_24h,
    "CONS": lambda s: s.pool.consistency,
    "LIVE": lambda s: s.pool.liveness,
    "σ%": lambda s: s.pool.volatility,
    "DD24": lambda s: s.pool.drawdown24h,
    "MY$/D": lambda s: s.sim.fee_day if s.sim else 0.0,
    "NET$/D": lambda s: s.sim.net_day if s.sim else 0.0,
    "SHARE": lambda s: s.sim.share if s.sim else 0.0,
    "SCORE": lambda s: s.score,
    "RK": lambda s: s.grade,
    "LINKS": lambda s: s.n_links,
    "AGE": lambda s: s.pool.seen_days or 0.0,
    "TX1H": lambda s: s.flow.tx_h1 if s.flow else -1,
    "TX24": lambda s: s.flow.tx_h24 if s.flow else -1,
}
SORT_ORDER = [c for c in COLUMNS if c in SORTABLE]
# text columns and risk columns read naturally ascending
ASC_DEFAULT = {"PAIR", "PROTO", "σ%", "RK", "SHARE"}


class LinksModal(ModalScreen[str | None]):
    """Popup listing the pool page and every social link; Enter/click opens, Esc closes."""

    BINDINGS: ClassVar = [Binding("escape", "dismiss(None)", "CLOSE")]

    def __init__(self, pool: Pool, links: list[tuple[str, str, str]]) -> None:
        super().__init__()
        self.pool = pool
        self.links = links

    def compose(self) -> ComposeResult:
        opts = [
            Option(Text.assemble(("KRYSTAL ", "bold #ffb000"), self.pool.url), id=self.pool.url)
        ]
        for sym, label, url in self.links:
            opts.append(
                Option(
                    Text.assemble(
                        (f"{sym:<10}", "bold white"), (f"{label:<7}", "bold #ffb000"), url
                    ),
                    id=url,
                )
            )
        with Vertical(id="links_box") as box:
            box.border_title = f"LINKS  {self.pool.pair}"
            yield OptionList(*opts, id="links_list")
            yield Static("enter/click open   esc close", id="links_help")

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected) -> None:
        self.dismiss(str(ev.option.id))


class RotationModal(ModalScreen[str | None]):
    """Full rotation list for one position; Enter/click jumps the screener to that pool."""

    BINDINGS: ClassVar = [Binding("escape", "dismiss(None)", "CLOSE")]

    def __init__(self, pos: Position, rot: Rotation, profile_name: str) -> None:
        super().__init__()
        self.pos = pos
        self.rot = rot
        self.profile_name = profile_name

    def compose(self) -> ComposeResult:
        opts: list[Option] = []
        for cd in self.rot.candidates:
            pb = f"{_days(cd.payback_days):>6}"
            line = Text.assemble(
                (f"{cd.pool.pair:<18}", "bold white"),
                (f"{cd.pool.protocol:<10}", "cyan"),
                (f"{cd.pool.fee_tier_pct:>5.2f}%  ", ""),
                (f"{cd.scored.grade}  ", "bold"),
                (f"net {cd.sim.net_day:>+8,.0f}$/d  ", "green" if cd.sim.net_day > 0 else "red"),
                (f"uplift {cd.uplift_day:>+8,.0f}$/d  ", "green" if cd.uplift_day > 0 else "red"),
                (f"payback {pb}  ", ""),
                (f"share {cd.sim.share * 100:>5.1f}%  ", "red" if cd.sim.share >= 0.25 else ""),
                (f"fee/IL {cd.sim.fee_il_ratio:>5.1f}×", "dim"),
            )
            opts.append(Option(line, id=cd.pool.address))
        with Vertical(id="rot_box") as box:
            box.border_title = (
                f"ROTATE {self.pos.pair} ({self.pos.value:,.0f}$)  profile {self.profile_name}"
            )
            yield Static(
                Text.assemble(
                    (self.rot.verdict + "\n", "bold #ffb000"),
                    (
                        (
                            f"current net {self.rot.current_net_day:+,.0f}$/d   "
                            f"switch cost {self.rot.cost:,.0f}$   enter = screen pool   esc close"
                        ),
                        "dim",
                    ),
                ),
                id="rot_head",
            )
            yield OptionList(*opts, id="rot_list")

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected) -> None:
        self.dismiss(str(ev.option.id))


class TrackScreen(Screen[None]):
    """Closed-position analytics + equity history per vault."""

    BINDINGS: ClassVar = [
        Binding("escape", "dismiss(None)", "BACK"),
        Binding("tab", "next_vault", "NEXT VAULT"),
    ]

    def __init__(self, app_ref: CuratorApp) -> None:
        super().__init__()
        self.curator = app_ref
        self.idx = 0

    def compose(self) -> ComposeResult:
        yield Static("", id="track_topbar")
        body = Static("", id="track_body")
        body.border_title = "TRACK RECORD"
        yield body
        yield Footer()

    def on_mount(self) -> None:
        self._draw()

    def action_next_vault(self) -> None:
        if self.curator.vaults:
            self.idx = (self.idx + 1) % len(self.curator.vaults)
            self._draw()

    def _draw(self) -> None:
        vs = self.curator.vaults
        if not vs:
            return
        v = vs[self.idx]
        tr = track_record(v.closed)
        idle, idle_pct = idle_capital(v)
        gain, roi = real_roi(v)
        self.query_one("#track_topbar", Static).update(
            f" TRACK RECORD   {v.name}   ({self.idx + 1}/{len(vs)}, tab = next)   "
            f"{v.vault_type}  tvl {v.tvl:,.0f}$  apr {v.apr:.1f}%  risk {v.risk}"
        )
        t = Table.grid(padding=(0, 1), expand=True)
        t.add_column(style="#ffb000", no_wrap=True)
        t.add_column(style="white")

        # ---- equity
        hist = self.curator.store.vault_history(v.chain_id, v.address, days=30)
        eq = Text()
        if len(hist) >= 2:
            span = (hist[-1].ts - hist[0].ts) / 3600
            eq.append(f"{len(hist)} samples / {span:.0f}h   ", style="dim")
            eq.append("tvl ", style="#ffb000")
            eq.append(sparkline([h.tvl for h in hist], 30), style="#ffb000")
            eq.append(f"  {hist[0].tvl:,.0f} → {hist[-1].tvl:,.0f}$\n")
            eq.append(" " * 25 + "pnl ", style="cyan")
            eq.append(sparkline([h.pnl for h in hist], 30), style="cyan")
            eq.append(f"  {hist[0].pnl:+,.0f} → {hist[-1].pnl:+,.0f}$\n")
            eq.append(" " * 24 + "24h$ ", style="green")
            eq.append(sparkline([h.earning24h for h in hist], 30), style="green")
            eq.append(f"  {hist[-1].earning24h:+,.0f}$/d now")
        else:
            eq.append("building — needs ≥2 refreshes 5 min apart", style="dim")
        t.add_row("EQUITY", eq)
        t.add_row(
            "CAPITAL",
            Text.assemble(
                (f"tvl {v.tvl:,.0f}$   deployed {v.tvl - idle:,.0f}$   ", ""),
                (
                    f"idle {idle:,.0f}$ ({idle_pct * 100:.1f}%)",
                    "red" if idle_pct >= 0.3 else "yellow" if idle_pct >= 0.1 else "green",
                ),
                ("   ← capital not earning" if idle_pct >= 0.1 else "", "dim"),
            ),
        )
        t.add_row(
            "SINCE START",
            Text.assemble(
                (
                    f"deposited {v.my_deposit:,.0f}$   withdrawn {v.my_withdrawn:,.0f}$   value {v.my_value:,.0f}$   ",
                    "",
                ),
                (
                    f"net {gain:+,.0f}$" + (f" ({roi * 100:+.1f}%)" if roi is not None else ""),
                    "bold green" if gain >= 0 else "bold red",
                ),
                (f"   lifetime fees {v.fee_generated:,.0f}$   30d {v.earning_30d:+,.0f}$", "dim"),
            ),
        )
        t.add_row("", "")

        # ---- closed stats
        if tr.n == 0:
            t.add_row("CLOSED", Text("no closed positions yet", style="dim"))
        else:
            st = Table.grid(padding=(0, 2))
            st.add_column(style="#ffb000", no_wrap=True)
            st.add_column(style="white")
            st.add_row(
                "count",
                Text.assemble(
                    (f"{tr.n} closed   win rate ", ""),
                    (
                        f"{tr.win_rate * 100:.0f}%",
                        "bold green" if tr.win_rate >= 0.5 else "bold red",
                    ),
                    (
                        f"   avg hold {tr.avg_hold_days:.1f}d   avg deposit {tr.avg_deposit:,.0f}$",
                        "",
                    ),
                ),
            )
            st.add_row(
                "realised",
                Text.assemble(
                    (f"{tr.pnl:+,.0f}$ total", "bold green" if tr.pnl >= 0 else "bold red"),
                    (f"   = fees {tr.fees:+,.0f}$ + price {tr.price_pnl:+,.0f}$   ", ""),
                    (
                        f"avg {tr.avg_pnl:+,.0f}$  median {tr.median_pnl:+,.0f}$  {tr.pnl_per_day:+,.1f}$/position-day",
                        "dim",
                    ),
                ),
            )
            if tr.best and tr.worst:
                st.add_row(
                    "best / worst",
                    Text.assemble(
                        (f"{tr.best.pair} {tr.best.pnl:+,.0f}$ ({tr.best.age_days:.1f}d)", "green"),
                        ("   ", ""),
                        (
                            f"{tr.worst.pair} {tr.worst.pnl:+,.0f}$ ({tr.worst.age_days:.1f}d)",
                            "red",
                        ),
                    ),
                )
            t.add_row("CLOSED", st)
            t.add_row("", "")

            def bucket_table(title: str, buckets) -> Table:
                b = Table(box=None, pad_edge=False, header_style="bold #ffb000")
                b.add_column(title)
                b.add_column("N", justify="right")
                b.add_column("WIN", justify="right")
                b.add_column("PNL", justify="right")
                b.add_column("FEES", justify="right")
                b.add_column("PRICE", justify="right")
                b.add_column("AVG", justify="right")
                b.add_column("HOLD", justify="right")
                for x in buckets:
                    b.add_row(
                        Text(x.key, style="white"),
                        str(x.n),
                        _color_num(f"{x.win_rate * 100:.0f}%", x.win_rate, 0.6, 0.4),
                        _color_num(f"{x.pnl:+,.0f}", x.pnl, 0.0, -1e-9),
                        f"{x.fees:,.0f}",
                        _color_num(f"{x.pnl - x.fees:+,.0f}", x.pnl - x.fees, 0.0, -1e-9),
                        f"{x.avg_pnl:+,.0f}",
                        f"{x.avg_hold_days:.1f}d",
                    )
                return b

            side = Table.grid(padding=(0, 4))
            side.add_column()
            side.add_column()
            side.add_row(
                bucket_table("BY PROTOCOL", tr.by_protocol), bucket_table("BY FEE TIER", tr.by_tier)
            )
            t.add_row("BREAKDOWN", side)
            t.add_row("", "")
            t.add_row("BY PAIR", bucket_table("PAIR", tr.by_pair[:25]))
        self.query_one("#track_body", Static).update(t)


POS_COLUMNS = (
    "VAULT",
    "PAIR",
    "PROTO",
    "STATUS",
    "RANGE",
    "VALUE",
    "DEPOSIT",
    "PNL",
    "ROI%",
    "FEES",
    "PEND",
    "APR",
    "AGE",
    "POOL RK",
    "POOL Y24%",
    "POOL σ%",
)


class PositionsScreen(Screen[str | None]):
    """Positions inside your Krystal vaults (public API) plus, with a Cloud key, LP NFTs
    held directly by the wallet. Enter jumps the screener to that pool."""

    BINDINGS: ClassVar = [
        Binding("escape", "dismiss(None)", "BACK"),
        Binding("r", "refresh", "REFRESH"),
        Binding("c", "toggle_closed", "CLOSED"),
        Binding("x", "rotate", "ROTATE?"),
        Binding("t", "track", "TRACK"),
        Binding("e", "report", "REPORT"),
        Binding("1", "profile('conservative')", "CONS", show=False),
        Binding("2", "profile('balanced')", "BAL", show=False),
        Binding("3", "profile('aggressive')", "AGG", show=False),
        Binding("4", "profile('degen')", "DEGEN", show=False),
        Binding("o", "open_url", "OPEN"),
        Binding("enter", "jump", "SCREEN POOL", show=True),
    ]

    def __init__(self, app_ref: CuratorApp) -> None:
        super().__init__()
        self.curator = app_ref
        self.show_closed = False
        self._order: list[Position] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="pos_topbar")
        with Horizontal(id="pos_body"):
            table = DataTable(id="pos_table", cursor_type="row")
            table.border_title = "MY POSITIONS"
            yield table
            detail = Static("", id="pos_detail")
            detail.border_title = "POSITION DETAIL"
            yield detail
        yield Static("", id="pos_vaults")
        yield Static("", id="pos_status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#pos_table", DataTable)
        table.add_columns(*POS_COLUMNS)
        table.fixed_columns = 2
        self._topbar()
        if self.curator.vaults or self.curator.positions:
            self._fill()
        else:
            self.action_refresh()

    # ---- data -----------------------------------------------------------
    def action_refresh(self) -> None:
        self.query_one("#pos_status", Static).update("fetching vaults + positions …")
        self._fetch()

    @work(thread=True, exclusive=True, group="positions")
    def _fetch(self) -> None:
        wallet = self.curator.wallet or ""
        try:
            vaults = fetch_vaults(wallet, chain_id=self.curator.chain_id)
        except KrystalError as e:
            self.app.call_from_thread(self._error, str(e))
            return
        direct: list[Position] | None = None
        err = ""
        if self.curator.cloud_key:
            try:
                direct = fetch_positions(
                    self.curator.cloud_key, wallet, chain_ids=[self.curator.chain_id]
                )
            except KrystalError as e:
                err = str(e)
        self.app.call_from_thread(self._loaded, vaults, direct, err)

    def _error(self, msg: str) -> None:
        self.query_one("#pos_status", Static).update(Text(f"ERROR {msg}", style="bold red"))

    def _loaded(self, vaults: list[Vault], direct: list[Position] | None, err: str) -> None:
        self.curator.vaults = vaults
        if direct is not None:
            self.curator.units_used += POSITIONS_UNITS
            self.curator.positions = direct
        self.curator.monitor.direct = self.curator.positions
        self.curator.monitor.vaults = vaults
        for a in self.curator.monitor._position_alerts():
            self.app.notify(a.text, title=a.title, severity=a.severity, timeout=30)
        self._fill()
        if err:
            self.query_one("#pos_status", Static).update(
                Text(f"vaults ok; cloud positions failed: {err}", style="yellow")
            )

    def _open_positions(self) -> list[Position]:
        return [p for v in self.curator.vaults for p in v.positions] + list(self.curator.positions)

    def _closed_positions(self) -> list[Position]:
        return [p for v in self.curator.vaults for p in v.closed]

    # ---- render ---------------------------------------------------------
    def _topbar(self) -> None:
        w = self.curator.wallet or ""
        opens = self._open_positions()
        value = sum(p.value for p in opens)
        pnl = sum(p.pnl for p in opens)
        pend = sum(p.fee_pending for p in opens)
        out = sum(1 for p in opens if not p.in_range)
        e24 = sum(v.earning_24h for v in self.curator.vaults)
        cloud = f"   CLOUD:{self.curator.units_used}u" if self.curator.cloud_key else ""
        self.query_one("#pos_topbar", Static).update(
            f" MY POSITIONS   {w[:6]}…{w[-4:]}   ROBINHOOD({self.curator.chain_id})   "
            f"{len(self.curator.vaults)} vaults   {len(opens)} open, {out} out of range   "
            f"VALUE ${value:,.0f}   PNL {pnl:+,.0f}$   PENDING {pend:,.0f}$   "
            f"VAULT EARN 24H {e24:,.0f}${cloud}"
        )

    def _vault_lines(self) -> Text:
        t = Text()
        for v in self.curator.vaults:
            wr = f"{v.win_rate * 100:.0f}%" if v.win_rate is not None else "-"
            t.append(f" {v.name} ", style="bold black on #ffb000")
            t.append(f" {v.vault_type} {'owned' if v.owned else 'joined'}  ", style="dim")
            t.append(f"tvl {v.tvl:,.0f}$  ")
            t.append(f"pnl {v.pnl:+,.0f}$  ", style="green" if v.pnl >= 0 else "red")
            t.append(f"apr {v.apr:.1f}%  24h {v.earning_24h:+,.0f}$  30d {v.earning_30d:+,.0f}$  ")
            idle, idle_pct = idle_capital(v)
            t.append(
                f"idle {idle:,.0f}$ ({idle_pct * 100:.0f}%)  ",
                style="red" if idle_pct >= 0.3 else "yellow" if idle_pct >= 0.1 else "dim",
            )
            gain, roi = real_roi(v)
            t.append(
                f"since inception {gain:+,.0f}$"
                + (f" ({roi * 100:+.1f}%)  " if roi is not None else "  "),
                style="green" if gain >= 0 else "red",
            )
            t.append(
                f"closed {len(v.closed)} (win {wr}, pnl {v.closed_pnl:+,.0f}$)  ",
                style="dim",
            )
            hist = self.curator.store.vault_history(v.chain_id, v.address, days=30)
            if len(hist) >= 2:
                t.append("tvl ", style="dim")
                t.append(sparkline([h.tvl for h in hist], 16), style="#ffb000")
                t.append("  ", style="dim")
            t.append(f"risk {v.risk}  age {v.age_days:.0f}d\n", style="dim")
        self.query_one("#pos_vaults", Static).update(t)

    def _fill(self) -> None:
        table = self.query_one("#pos_table", DataTable)
        table.clear()
        rows = self._open_positions() + (self._closed_positions() if self.show_closed else [])
        self._order = sorted(rows, key=lambda x: (x.status == "CLOSED", -x.value))
        for n, p in enumerate(self._order):
            sc = self.curator.pool_for(p.pool_address, p.pool_alt)
            pool = sc.pool if sc else None
            rp = p.range_pos
            if p.status == "CLOSED":
                st = Text("CLOSED", style="dim")
                rng = Text("", style="dim")
            else:
                st = Text(
                    "IN" if p.in_range else p.status,
                    style="bold green" if p.in_range else "bold red",
                )
                if rp is None:
                    rng = Text("?", style="dim")
                else:
                    bar = ["─"] * 10
                    bar[max(0, min(9, int(rp * 10)))] = "●"
                    rng = Text("".join(bar), style="green" if 0 <= rp <= 1 else "red")
            table.add_row(
                Text(p.vault or "wallet", style="#ffb000"),
                Text(p.pair, style="bold white"),
                Text(p.protocol, style="cyan"),
                st,
                rng,
                Text(f"{p.value:,.0f}", justify="right", style="bold"),
                Text(f"{p.deposit:,.0f}", justify="right"),
                _color_num(f"{p.pnl:+,.0f}", p.pnl, 0.0, -1e-9),
                _color_num(f"{p.roi_pct:+.1f}", p.roi_pct, 0.0, -1e-9),
                Text(f"{p.fee_claimed:,.0f}", justify="right"),
                Text(f"{p.fee_pending:,.0f}", justify="right", style="bold yellow"),
                Text(f"{p.fee_apr:,.1f}%", justify="right"),
                Text(f"{p.age_days:.1f}d", justify="right"),
                _grade_text(sc.grade) if sc else Text("-", style="dim"),
                Text(f"{pool.fee_yield_24h * 100:.2f}" if pool else "-", justify="right"),
                Text(f"{pool.volatility:.1f}" if pool else "-", justify="right"),
                key=f"{n}:{p.id}",
            )
        self._topbar()
        self._vault_lines()
        if self._order:
            table.move_cursor(row=0)
            self._render_detail(self._order[0])
        else:
            self.query_one("#pos_detail", Static).update(Text("no positions", style="dim"))
        closed = "hide" if self.show_closed else "show"
        self.query_one("#pos_status", Static).update(
            f"{len(self._open_positions())} open, {len(self._closed_positions())} closed   r refresh   c {closed} closed   "
            f"enter = screen this pool   o open vault   esc back"
        )

    def _render_detail(self, p: Position) -> None:
        c = self.curator
        sc = c.pool_for(p.pool_address, p.pool_alt)
        pool = sc.pool if sc else None
        adv = c.advice_for(p)
        t = Table.grid(padding=(0, 1), expand=True)
        t.add_column(style="#ffb000", no_wrap=True)
        t.add_column(style="white")
        st_style = "bold green" if p.in_range else "dim" if p.status == "CLOSED" else "bold red"
        t.add_row(
            "POSITION",
            Text.assemble(
                (f"{p.pair}  ", "bold white"),
                (f"[{p.protocol}]  ", "cyan"),
                (p.vault or "wallet", "#ffb000"),
                ("  ", ""),
                (p.status, st_style),
            ),
        )
        t.add_row("", "")

        # ---- range ladder + edges
        t.add_row("RANGE", Text(price_ladder(p, 44), style="#ffb000"))
        t.add_row(
            "",
            f"min {p.min_price:,.4g}   now {p.current_price:,.4g}   max {p.max_price:,.4g}"
            f"   half-width ±{adv.width_pct:.1f}%"
            if p.current_price
            else "range unknown",
        )
        sig = c.sigma_for(p)
        if sig is not None and pool is not None:
            t.add_row(
                "",
                Text(
                    f"pool σ {sig:.1f}%/day  →  7d 1σ range would be ±{sig * 7**0.5:.1f}%",
                    style="dim",
                ),
            )
        e = Table(box=None, pad_edge=False, expand=True, header_style="bold #ffb000")
        e.add_column("EDGE")
        e.add_column("PRICE", justify="right")
        e.add_column("DIST", justify="right")
        e.add_column("σ", justify="right")
        e.add_column("~DAYS", justify="right")
        e.add_column("")
        for ed in (adv.lower, adv.upper):
            if ed is None:
                continue
            urg = ed.urgency
            style = {"CRITICAL": "bold red", "close": "red", "watch": "yellow", "ok": "green"}.get(
                urg, "dim"
            )
            e.add_row(
                ed.name,
                f"{ed.price:,.4g}",
                f"{ed.dist_pct:.1f}%",
                f"{ed.sigmas:.1f}" if ed.sigmas is not None else "-",
                f"{ed.days:.1f}" if ed.days is not None else "-",
                Text(urg, style=style),
            )
        t.add_row("EDGES", e)
        t.add_row("", "")

        # ---- performance
        perf = Table.grid(padding=(0, 2))
        perf.add_column(style="#ffb000", no_wrap=True)
        perf.add_column(style="white")
        perf.add_row(
            "value", f"{p.value:,.0f}$   deposit {p.deposit:,.0f}$   held {adv.hold_days:.1f}d"
        )
        perf.add_row(
            "pnl",
            Text(f"{p.pnl:+,.0f}$  ({p.roi_pct:+.2f}%)", style="green" if p.pnl >= 0 else "red"),
        )
        perf.add_row(
            "fees",
            f"{p.fees_total:,.2f}$ total, {p.fee_pending:,.2f}$ pending   "
            f"realised {adv.fee_per_day:,.2f}$/d = {adv.fee_yield_day * 100:.3f}%/d",
        )
        if pool is not None:
            ratio = adv.fee_yield_day / pool.fee_yield_24h if pool.fee_yield_24h > 0 else 0
            perf.add_row(
                "vs pool",
                f"pool fee yield {pool.fee_yield_24h * 100:.3f}%/d  →  you capture {ratio:.2f}× "
                f"({'concentrated' if ratio > 1.2 else 'diluted' if ratio < 0.8 else 'on par'})",
            )
        perf.add_row("apr", f"{p.fee_apr:.2f}% (Krystal, 24h basis)")
        t.add_row("PERF", perf)
        t.add_row("", "")

        # ---- rotation / opportunity cost
        if p.status != "CLOSED" and p.value > 0:
            rot = c.rotation_for(p, top=5)
            r = Table(box=None, pad_edge=False, expand=True, header_style="bold #ffb000")
            r.add_column("POOL")
            r.add_column("RK", justify="center")
            r.add_column("MY$/D", justify="right")
            r.add_column("IL/D", justify="right")
            r.add_column("NET/D", justify="right")
            r.add_column("SHARE", justify="right")
            r.add_column("UPLIFT", justify="right")
            r.add_column("PAYBACK", justify="right")
            cur_il = rot.current_sim.il_day if rot.current_sim else 0.0
            r.add_row(
                Text("current (realised)", style="bold white"),
                _grade_text(sc.grade) if sc else Text("-"),
                f"{adv.fee_per_day:,.0f}",
                f"{cur_il:,.0f}",
                Text(f"{rot.current_net_day:+,.0f}", style="bold"),
                f"{rot.current_sim.share * 100:.1f}%" if rot.current_sim else "-",
                "",
                "",
            )
            for cd in rot.candidates:
                r.add_row(
                    Text(cd.pool.pair, style="white", no_wrap=True),
                    _grade_text(cd.scored.grade),
                    f"{cd.sim.fee_day:,.0f}",
                    f"{cd.sim.il_day:,.0f}",
                    _color_num(f"{cd.sim.net_day:+,.0f}", cd.sim.net_day, 1, 0),
                    _color_num(f"{cd.sim.share * 100:.1f}%", cd.sim.share, 0.0, 0.25, invert=True),
                    _color_num(f"{cd.uplift_day:+,.0f}", cd.uplift_day, 1, 0),
                    _days(cd.payback_days),
                )
            verdict_style = (
                "bold green"
                if rot.verdict.startswith("ROTATE")
                else "bold yellow"
                if rot.verdict.startswith("CONSIDER")
                else "bold white"
            )
            t.add_row(
                "ROTATE",
                Group(
                    Text(rot.verdict, style=verdict_style),
                    Text(
                        f"same {p.value:,.0f}$ in {c.profile.name.lower()} pools (1-4 to change), "
                        f"switch cost {rot.cost:,.0f}$ ({c.config.rotate_cost_pct}%), x = full list",
                        style="dim",
                    ),
                    r,
                ),
            )
            t.add_row("", "")

        # ---- what to type into Krystal's Automation form
        if p.status != "CLOSED":
            su = recommend(p, c.sigma_for(p), c.profile)
            k = Table(box=None, pad_edge=False, expand=True, header_style="bold #ffb000")
            k.add_column("SECTION", no_wrap=True, style="#ffb000")
            k.add_column("FIELD", no_wrap=True, style="bold white")
            k.add_column("VALUE", style="white")
            k.add_column("WHY", style="grey58")
            for section, fs in su.by_section().items():
                for i, f in enumerate(fs):
                    k.add_row(section if i == 0 else "", f.label, f.value, f.why)
            t.add_row(
                "KRYSTAL SETUP",
                Group(
                    Text(
                        f"copy into Automation → this position   ({c.profile.name.lower()}: "
                        f"±{su.range_pct:g}% range for ~{su.hold_days:g}d, 1-4 to change)",
                        style="dim",
                    ),
                    k,
                ),
            )
            t.add_row("", "")

        # ---- pool health from the screener
        if sc is not None and pool is not None:
            h = Table.grid(padding=(0, 2))
            h.add_column(style="#ffb000", no_wrap=True)
            h.add_column(style="white")
            h.add_row(
                "grade",
                Text.assemble(
                    (sc.grade, "bold"),
                    (f"   score {sc.score:.1f} ({c.profile.name.lower()})   ", ""),
                    (" ".join(sc.flags), "magenta"),
                ),
            )
            h.add_row(
                "24h",
                f"vol {pool.s24h.volume:,.0f}$  fee {pool.s24h.fee:,.0f}$  yield {pool.fee_yield_24h * 100:.3f}%/d"
                f"  turnover {pool.turnover_24h:.1f}x",
            )
            h.add_row(
                "signal",
                f"consistency {pool.consistency:.2f}   liveness {pool.liveness:.2f}   σ {pool.volatility:.1f}%"
                f"   dd24 {pool.drawdown24h:.1f}%",
            )
            axes = [(RADAR_LABEL.get(k, k.upper()), v) for k, v in sc.parts.items()]
            h.add_row("", render_radar(axes, cols=34, rows=11, show_values=False))
            t.add_row("POOL", h)
        else:
            t.add_row("POOL", Text("not in the LP explorer feed (no health data)", style="dim"))
        self.query_one("#pos_detail", Static).update(t)

    def on_data_table_row_highlighted(self, ev: DataTable.RowHighlighted) -> None:
        if ev.cursor_row is not None and 0 <= ev.cursor_row < len(self._order):
            self._render_detail(self._order[ev.cursor_row])

    # ---- actions --------------------------------------------------------
    def _selected(self) -> Position | None:
        i = self.query_one("#pos_table", DataTable).cursor_row
        return self._order[i] if 0 <= i < len(self._order) else None

    def action_toggle_closed(self) -> None:
        self.show_closed = not self.show_closed
        self._fill()

    def action_profile(self, key: str) -> None:
        self.curator.profile = PROFILES[key]
        p = self._selected()
        if p:
            self._render_detail(p)

    def action_track(self) -> None:
        if not self.curator.vaults:
            return
        self.app.push_screen(TrackScreen(self.curator))

    def action_report(self) -> None:
        if not self.curator.vaults:
            return
        equity = {
            v.address: [h.tvl for h in self.curator.store.vault_history(v.chain_id, v.address)]
            for v in self.curator.vaults
        }
        chain = next((v.chain for v in self.curator.pools[:1]), str(self.curator.chain_id))
        md = report_markdown(self.curator.vaults, chain=chain, equity=equity)
        out = Path("reports")
        out.mkdir(exist_ok=True)
        path = out / f"vaults_{self.curator.chain_id}_{datetime.now(UTC):%Y%m%d_%H%M}.md"
        path.write_text(md, encoding="utf-8")
        self.query_one("#pos_status", Static).update(f"report saved {path}")
        self.app.notify(f"saved {path}", title="REPORT")

    def action_rotate(self) -> None:
        p = self._selected()
        if p is None or p.status == "CLOSED":
            return
        rot = self.curator.rotation_for(p, top=20)
        self.app.push_screen(RotationModal(p, rot, self.curator.profile.name), self._on_rotate_pick)

    def _on_rotate_pick(self, address: str | None) -> None:
        if address:
            self.dismiss(address)

    def action_open_url(self) -> None:
        p = self._selected()
        if not p:
            return
        v = next((v for v in self.curator.vaults if v.name == p.vault), None)
        sc = self.curator.pool_for(p.pool_address, p.pool_alt)
        webbrowser.open(v.url if v else sc.pool.url if sc else "https://defi.krystal.app/account")

    def action_jump(self) -> None:
        p = self._selected()
        if p:
            sc = self.curator.pool_for(p.pool_address, p.pool_alt)
            self.dismiss(sc.pool.address if sc else p.pool_address)

    def on_data_table_row_selected(self, _: DataTable.RowSelected) -> None:
        self.action_jump()


class CuratorApp(App[None]):
    TITLE = "KRYSTAL CURATOR"
    CSS_PATH = "tui.tcss"
    BINDINGS: ClassVar = [
        Binding("1", "profile('conservative')", "CONS"),
        Binding("2", "profile('balanced')", "BAL"),
        Binding("3", "profile('aggressive')", "AGG"),
        Binding("4", "profile('degen')", "DEGEN"),
        Binding("u", "toggle_quote", "USDG"),
        Binding("p", "cycle_protocol", "PROTO"),
        Binding("s", "cycle_sort", "SORT"),
        Binding("S", "reverse_sort", "ASC/DESC"),
        Binding("r", "refresh", "REFRESH"),
        Binding("a", "toggle_auto", "AUTO"),
        Binding("asterisk", "toggle_watch", "WATCH", key_display="*"),
        Binding("W", "watch_only", "★ONLY"),
        Binding("P", "positions", "MY POS"),
        Binding("o", "open_url", "OPEN"),
        Binding("l", "links", "LINKS"),
        Binding("e", "export_csv", "CSV"),
        Binding("slash", "find", "FIND", key_display="/"),
        Binding("dollar_sign", "size", "SIZE", key_display="$"),
        Binding("escape", "clear_find", "", show=False),
        Binding("q", "quit", "QUIT"),
    ]

    def __init__(
        self,
        *,
        chain_id: int,
        profile: str = "balanced",
        quote: str | None = "USDG",
        protocols: set[str] | None = None,
        image_mode: str | None = None,
        size: float = 50_000,
        refresh_seconds: int = 300,
        wallet: str | None = None,
        config: Config | None = None,
    ) -> None:
        super().__init__()
        self.config = config or Config()
        self.wallet = wallet or api.wallet()
        self.units_used = 0  # Cloud API units spent this session
        self.positions: list[Position] = []  # direct wallet positions (Cloud API)
        self.vaults: list[Vault] = []  # vault positions (public API)
        self.position_size = size
        self.refresh_seconds = refresh_seconds if refresh_seconds > 0 else 300
        self.auto = refresh_seconds > 0
        self.watch_only = False
        self.store = Store()
        self._hist_cache: dict[str, tuple[Delta, str]] = {}
        self.monitor = Monitor(
            self.store,
            profile=PROFILES[profile],
            alerts=self.config.alerts,
            snapshot_days=self.config.snapshot_days,
        )
        self._timer = None
        self.image_mode = pick_image_mode(image_mode)
        self.image_cls = IMAGE_MODES[self.image_mode]
        self.chain_id = chain_id
        self.profile: RiskProfile = PROFILES[profile]
        self.quote: str | None = quote
        self.quote_default = quote or "USDG"
        self.protocol_filter: str | None = None  # None = all
        self.available_protocols: list[str] = sorted(protocols) if protocols else []
        self.sort_col = "SCORE"
        self.sort_desc = True
        self.pools: list[Pool] = []
        self.rows: list[Scored] = []
        self.find_text = ""
        self.last_refresh: datetime | None = None
        self.cloud_key = api.cloud_key()
        self.meta = TokenMeta()
        self.flows = FlowCache()
        self.infos: dict[str, TokenInfo] = {}  # for the selected pool, by address
        self.infos_all: dict[str, TokenInfo] = {}  # every token seen in the table, by address

    # ---- layout ---------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Static("", id="topbar")
        with Vertical(id="body"):
            with Horizontal():
                table = DataTable(id="table", cursor_type="row", zebra_stripes=False)
                table.border_title = "POOL SCREEN"
                yield table
                with Vertical(id="detail") as detail:
                    detail.border_title = "POOL DETAIL"
                    with Horizontal(id="hero"):
                        if self.image_cls is not None:
                            yield self.image_cls(None, id="logo0")
                            yield self.image_cls(None, id="logo1")
                        yield Static("", id="hero_text")
                    yield Static("", id="detail_body")
            yield Input(placeholder="find pair / token …", id="find")
            yield Input(placeholder="position size in USD, e.g. 50000", id="size", type="number")
            yield Static("", id="status")
        yield Footer()

    @property
    def main(self) -> Screen:
        """The base screen; widgets live here even while a modal is on top."""
        return self.screen_stack[0]

    def on_mount(self) -> None:
        table = self.main.query_one("#table", DataTable)
        table.fixed_columns = 2
        self._render_topbar()
        self._set_status("loading …")
        self.action_refresh()
        if self.auto:
            self._timer = self.set_interval(self.refresh_seconds, self._auto_tick)

    def _auto_tick(self) -> None:
        if self.auto:
            self._fetch()

    # ---- data -----------------------------------------------------------
    @work(thread=True, exclusive=True, group="fetch")
    def _fetch(self) -> None:
        try:
            pools = api.fetch_pools(self.chain_id)
        except api.KrystalError as e:
            self.call_from_thread(self._set_status, f"ERROR {e}")
            return
        vaults: list[Vault] | None = None
        if self.wallet:
            try:
                vaults = fetch_vaults(self.wallet, chain_id=self.chain_id)
            except KrystalError as e:
                self.call_from_thread(self.notify, str(e), title="VAULTS", severity="error")
        self.call_from_thread(self._on_pools, pools, vaults)

    def _on_pools(self, pools: list[Pool], vaults: list[Vault] | None = None) -> None:
        self.pools = pools
        self.last_refresh = datetime.now(UTC)
        if not self.available_protocols:
            self.available_protocols = sorted({p.protocol for p in pools})
        self.monitor.profile = self.profile
        self.monitor.direct = self.positions
        for a in self.monitor.tick(pools, vaults):
            self.notify(a.text, title=a.title, severity=a.severity, timeout=30)
        if vaults is not None:
            self.vaults = vaults
        self._hist_cache.clear()
        self._rebuild()

    # ---- position monitoring (runs on every refresh, free API) ------------
    def open_positions(self) -> list[Position]:
        return [p for v in self.vaults for p in v.positions] + list(self.positions)

    def sigma_for(self, p: Position) -> float | None:
        sc = self.pool_for(p.pool_address, p.pool_alt)
        return sc.pool.volatility if sc else None

    def advice_for(self, p: Position) -> Advice:
        return advise(p, self.sigma_for(p), alert_sigma=self.config.alerts.edge_sigma)

    def rotation_for(self, p: Position, top: int = 8) -> Rotation:
        sc = self.pool_for(p.pool_address, p.pool_alt)
        return plan(
            p,
            self.advice_for(p).fee_per_day,
            self.pools,
            self.profile,
            quote=self.quote,
            current_pool=sc.pool if sc else None,
            top=top,
            cost_pct=self.config.rotate_cost_pct,
        )

    def _hist(self, p: Pool) -> tuple[Delta, str]:
        key = p.address + p.protocol
        if key not in self._hist_cache:
            pts = self.store.history(p, hours=48)
            self._hist_cache[key] = (
                self.store.delta(p, hours=24),
                sparkline([x.fee24 for x in pts], 8),
            )
        return self._hist_cache[key]

    def _current_rows(self) -> list[Scored]:
        protos = {self.protocol_filter} if self.protocol_filter else None
        rows = curate(self.pools, self.profile, quote=self.quote, protocols=protos)
        if self.find_text:
            ft = self.find_text.upper()
            rows = [r for r in rows if ft in r.pool.pair.upper() or ft in r.pool.address.upper()]
        if self.watch_only:
            rows = [r for r in rows if self.store.is_watched(r.pool)]
        for r in rows:
            r.n_links = len(self._pool_links(r.pool))
            r.sim = simulate(r.pool, self.position_size)
            r.watched = self.store.is_watched(r.pool)
            r.delta, r.spark = self._hist(r.pool)
            r.flow = self.flows.get(r.pool.address)
        rows.sort(key=SORTABLE[self.sort_col], reverse=self.sort_desc)
        return rows

    # ---- links helpers --------------------------------------------------
    def _pool_links(self, p: Pool) -> list[tuple[str, str, str]]:
        """(token symbol, label, url) for both tokens, base token first."""
        order = (
            [(p.token1, p.token1_addr), (p.token0, p.token0_addr)]
            if p.token0.upper() == (self.quote or "USDG").upper()
            else [(p.token0, p.token0_addr), (p.token1, p.token1_addr)]
        )
        out: list[tuple[str, str, str]] = []
        for sym, addr in order:
            info = self.infos_all.get(addr) or self.meta.get(p.chain_id, addr)
            for label, url in info.links if info else []:
                out.append((sym, label, url))
        return out

    def _links_cell(self, p: Pool) -> Text:
        links = self._pool_links(p)
        known = all(
            (a in self.infos_all or self.meta.get(p.chain_id, a))
            for a in (p.token0_addr, p.token1_addr)
            if a
        )
        if not known:
            return Text("…", style="dim")
        if not links:
            return Text("-", style="dim")
        core = ("WEB", "X", "TG", "DC")
        labels = {label for _, label, _ in links}
        t = Text()
        for label in core:
            if label in labels:
                t.append(label, style="bold black on #ffb000")
                t.append(" ")
        extra = sum(1 for _, label, _ in links if label not in core)
        if extra:
            t.append(f"+{extra}", style="dim")
        return t

    def _column_labels(self) -> list[Text]:
        out: list[Text] = []
        for c in COLUMNS:
            if c == self.sort_col:
                out.append(
                    Text(f"{c}{'▼' if self.sort_desc else '▲'}", style="bold white on #5a3a00")
                )
            else:
                out.append(Text(c))
        return out

    def _rebuild(self) -> None:
        prev = self._selected()
        prev_key = prev.pool.address + prev.pool.protocol if prev else None
        self.rows = self._current_rows()
        table = self.main.query_one("#table", DataTable)
        table.clear(columns=True)
        for label, name in zip(self._column_labels(), COLUMNS, strict=True):
            table.add_column(label, key=name)
        for i, s in enumerate(self.rows, 1):
            p = s.pool
            table.add_row(
                Text(str(i), justify="right", style="dim"),
                Text("★" if s.watched else "", style="bold #ffb000"),
                Text(p.pair, style="bold white"),
                Text(p.protocol, style="cyan"),
                Text(_pct(p.fee_tier_pct), justify="right"),
                Text(_usd(p.tvl), justify="right"),
                Text(_usd(p.s24h.volume), justify="right"),
                Text(_usd(p.s24h.fee), justify="right", style="bold yellow"),
                _delta_text(s.delta.fee24_pct if s.delta else None),
                Text(s.spark, style="#ffb000"),
                Text(_usd(p.s7d.fee / 7), justify="right"),
                _color_num(_pct(p.fee_yield_24h * 100), p.fee_yield_24h, 0.01, 0.0005),
                _color_num(_pct(p.fee_yield_7d_daily * 100), p.fee_yield_7d_daily, 0.01, 0.0005),
                _color_num(_pct(p.turnover_24h, 1), p.turnover_24h, 2, 0.3),
                _color_num(_pct(p.consistency), p.consistency, 0.7, 0.0)
                if p.consistency <= 1.5
                else Text(_pct(p.consistency), style="bold red", justify="right"),
                _color_num(_pct(p.liveness), p.liveness, 0.8, 0.2),
                _tx_cell(s.flow, "h1"),
                _tx_cell(s.flow, "h24"),
                _color_num(_pct(p.volatility, 1), p.volatility, 10, 40, invert=True),
                _color_num(_pct(p.drawdown24h, 1), abs(p.drawdown24h), 10, 40, invert=True),
                Text(_usd(s.sim.fee_day), justify="right", style="bold yellow"),
                _color_num(_usd(s.sim.net_day), s.sim.net_day, 1, 0),
                _color_num(f"{s.sim.share * 100:.1f}%", s.sim.share, 0.0, 0.25, invert=True),
                Text(f"{s.score:5.1f}", justify="right", style="bold #ffb000"),
                _grade_text(s.grade),
                _age_text(p),
                self._links_cell(p),
                Text(" ".join(s.flags), style="magenta"),
                key=p.address + p.protocol,
            )
        self._render_topbar()
        self._set_status(
            f"universe {len(self.pools)}  →  {len(self.rows)} pass   "
            f"sort {self.sort_col} {'desc' if self.sort_desc else 'asc'}   "
            f"{self.profile.blurb}"
        )
        self._enrich_table(self.rows)
        self._enrich_flow(self.rows)
        if self.rows:
            idx = next(
                (
                    i
                    for i, r in enumerate(self.rows)
                    if r.pool.address + r.pool.protocol == prev_key
                ),
                0,
            )
            table.move_cursor(row=idx)
            self._render_detail(self.rows[idx])
        else:
            self.main.query_one("#detail_body", Static).update(
                Text(
                    "no pool passes this profile — try 3/4 or press u to widen quote",
                    style="red",
                )
            )
            self.main.query_one("#hero_text", Static).update("")

    # ---- rendering ------------------------------------------------------
    def _render_topbar(self) -> None:
        ts = self.last_refresh.strftime("%H:%M:%S UTC") if self.last_refresh else "--:--:--"
        chain = next((p.chain for p in self.pools[:1]), str(self.chain_id)).upper()
        proto = (self.protocol_filter or "ALL").upper()
        quote = self.quote or "ANY"
        cloud = f"  CLOUD:{self.units_used}u" if self.cloud_key else ""
        img = f"  IMG:{self.image_mode.upper()}"
        size = f"   SIZE:${_usd(self.position_size)}"
        every = (
            f"{self.refresh_seconds // 60}m"
            if self.refresh_seconds >= 60
            else f"{self.refresh_seconds}s"
        )
        auto = f"   AUTO:{every}" if self.auto else "   AUTO:off"
        watch = f"   ★{len(self.store.watch)}" + ("(only)" if self.watch_only else "")
        pos = ""
        if self.wallet:
            opens = self.open_positions()
            oor = sum(1 for p in opens if not p.in_range)
            edge = sum(1 for p in opens if self.advice_for(p).alert)
            e24 = sum(v.earning_24h for v in self.vaults)
            pos = f"   POS:{len(opens)}"
            if oor:
                pos += f" OOR:{oor}"
            if edge:
                pos += f" EDGE:{edge}"
            pos += f" 24h{e24:+,.0f}$"
        self.main.query_one("#topbar", Static).update(
            f" KRYSTAL CURATOR   {chain}({self.chain_id})   QUOTE:{quote}   PROTO:{proto}   "
            f"PROFILE:{self.profile.name}{size}{auto}{watch}{pos}   {ts}{cloud}{img}"
        )

    def _set_status(self, msg: str) -> None:
        self.main.query_one("#status", Static).update(msg)

    def _render_detail(self, s: Scored) -> None:
        p = s.pool
        t = Table.grid(padding=(0, 1), expand=True)
        t.add_column(style="#ffb000", no_wrap=True)
        t.add_column(style="white")
        t.add_row(
            "PAIR",
            Text(f"{p.pair}  [{p.protocol}]  tier {p.fee_tier_pct:.3f}%", style="bold"),
        )
        t.add_row("POOL", Text(p.address, overflow="fold"))
        t.add_row("URL", Text(p.url, style=f"link {p.url} underline cyan", overflow="fold"))
        t.add_row("TVL", f"{p.tvl:,.0f}   grade {s.grade}   {' '.join(s.flags)}")
        t.add_row("HISTORY", self._history_line(p))
        t.add_row("", "")

        w = Table(box=None, pad_edge=False, expand=True, header_style="bold #ffb000")
        w.add_column("WINDOW")
        w.add_column("VOLUME", justify="right")
        w.add_column("FEE", justify="right")
        w.add_column("APR%", justify="right")
        w.add_column("FEE/TVL", justify="right")
        for name, st, days in (
            ("1H", p.s1h, 1 / 24),
            ("24H", p.s24h, 1),
            ("7D", p.s7d, 7),
            ("30D", p.s30d, 30),
        ):
            fy = st.fee / p.tvl / days * 100 if p.tvl > 0 else 0
            w.add_row(
                name,
                f"{st.volume:,.0f}",
                f"{st.fee:,.0f}",
                f"{st.apr:,.0f}",
                f"{fy:.2f}%/d",
            )
        t.add_row("STATS", w)
        t.add_row("", "")

        t.add_row(
            "RISK",
            f"σ {p.volatility:.1f}%   dd24 {p.drawdown24h:.1f}%   eff fee {p.effective_fee_pct:.3f}%",
        )
        t.add_row(
            "SIGNAL",
            f"turnover {p.turnover_24h:.2f}x   consistency {p.consistency:.2f}   liveness {p.liveness:.2f}",
        )
        f = s.flow or self.flows.get(p.address)
        if f is None:
            t.add_row("FLOW", Text("fetching swap counts …", style="dim"))
        elif f.tx_h24 == 0:
            t.add_row("FLOW", Text("no DexScreener data for this pool", style="dim"))
        else:
            b1 = f.buy_ratio_h1
            pace_style = "bold green" if f.pace >= 1.5 else "red" if f.pace < 0.3 else "white"
            t.add_row(
                "FLOW",
                Text.assemble(
                    (
                        f"swaps 5m {f.tx_m5:,}  1h {f.tx_h1:,}  6h {f.tx_h6:,}  24h {f.tx_h24:,}   ",
                        "",
                    ),
                    (f"pace {f.pace:.1f}×", pace_style),
                    (f"   avg trade {f.avg_trade_h24:,.0f}$   ", ""),
                    (
                        f"buys 1h {b1 * 100:.0f}%" if b1 is not None else "",
                        "green" if b1 and b1 > 0.6 else "red" if b1 and b1 < 0.4 else "",
                    ),
                ),
            )
        auto = "yes" if p.lp_auto else "NO"
        dyn = "dynamic" if p.dynamic_fee else "fixed"
        inc = (
            f"incentives {p.incentive_usd_day:,.0f}$/d (+{p.incentive_yield_day * 100:.2f}%/d)"
            if p.incentive_usd_day
            else "incentives none"
        )
        mm = p.fee_mismatch
        eff = f"   eff fee {p.effective_fee_pct:.3f}% vs tier {p.fee_tier_pct:.3f}%" + (
            f" ({mm * 100:+.0f}%)" if mm is not None else ""
        )
        t.add_row("MISC", f"lp-auto {auto}   fee {dyn}   {inc}{eff}")
        if p.tx24 is not None:
            t.add_row("TX24", f"{p.tx24:,}")
        t.add_row("", "")
        t.add_row(
            Text(f"${_usd(self.position_size)}", style="bold #ffb000"), self._position_table(s)
        )
        t.add_row("", "")

        b = Table(box=None, pad_edge=False, header_style="bold #ffb000")
        b.add_column("SCORE")
        b.add_column("W", justify="right")
        b.add_column("PTS", justify="right")
        axes: list[tuple[str, float]] = []
        for k, wt in self.profile.weights.items():
            pts = s.parts.get(k, 0.0)
            b.add_row(k, f"{wt:.0f}", Text(f"{pts:.2f}", style="#ffb000"))
            axes.append((RADAR_LABEL.get(k, k.upper()), pts))
        b.add_row(Text("TOTAL", style="bold"), "", Text(f"{s.score:.1f}", style="bold white"))
        chart = Table.grid(padding=(0, 2))
        chart.add_column()
        chart.add_column()
        chart.add_row(b, render_radar(axes, cols=36, rows=13, show_values=False))
        t.add_row(self.profile.name, chart)
        self.main.query_one("#detail_body", Static).update(
            Group(
                t,
                Text(""),
                Text.assemble(
                    ("LEGEND  ", "bold #ffb000"),
                    ("▲ higher raw = better   ▼ lower = better   ≈ near 1 = best", "grey70"),
                ),
                self._score_legend(s),
            )
        )
        self._render_hero(s)
        self._enrich(p)

    def _history_line(self, p: Pool) -> Text:
        pts = self.store.history(p, hours=48)
        d = self.store.delta(p, hours=24)
        t = Text()
        if len(pts) < 2:
            t.append("no local history yet — refreshes build it (r / auto)", style="dim")
            return t
        span_h = (pts[-1].ts - pts[0].ts) / 3600
        t.append(f"{len(pts)} snaps / {span_h:.0f}h   ", style="dim")
        t.append("fee ", style="#ffb000")
        t.append(sparkline([x.fee24 for x in pts], 16), style="#ffb000")
        t.append("  tvl ", style="cyan")
        t.append(sparkline([x.tvl for x in pts], 16), style="cyan")
        if d.hours is not None:
            t.append(f"   Δ{d.hours:.0f}h ", style="dim")
            for lab, v in (("tvl", d.tvl_pct), ("fee", d.fee24_pct), ("vol", d.vol24_pct)):
                if v is not None:
                    t.append(f"{lab} ")
                    t.append(f"{v:+.0f}%  ", style="green" if v >= 0 else "red")
        return t

    def _position_table(self, s: Scored) -> Table:
        """Position simulator for self.position_size USD in this pool."""
        sim = s.sim or simulate(s.pool, self.position_size)
        g = Table.grid(padding=(0, 2))
        g.add_column(style="#ffb000", no_wrap=True)
        g.add_column(style="white")
        crowd_style = {"ok": "green", "notable": "yellow"}.get(sim.crowding, "bold red")
        net_style = "bold green" if sim.net_day > 0 else "bold red"
        ratio = "∞" if sim.fee_il_ratio == math.inf else f"{sim.fee_il_ratio:.1f}×"
        be = "n/a" if sim.breakeven_days is None else f"{sim.breakeven_days:.1f}d"
        g.add_row(
            "share", Text(f"{sim.share * 100:.1f}% of pool   {sim.crowding}", style=crowd_style)
        )
        g.add_row(
            "fee/day",
            f"{sim.fee_day:,.0f}$   (7d basis {sim.fee_day_7d:,.0f}$)   apr {sim.apr:,.0f}%",
        )
        g.add_row("IL/day", f"{sim.il_day:,.0f}$   ({sim.il_day_pct:.2f}%/d, full-range σ²/8)")
        g.add_row("net/day", Text(f"{sim.net_day:+,.0f}$   fee covers IL {ratio}", style=net_style))
        g.add_row(
            "range 7d", f"±{sim.range_1s_7d:.1f}% holds 68%   ±{sim.range_2s_7d:.1f}% holds 95%"
        )
        g.add_row("breakeven", f"{be} of fees to cover a 2σ 7-day move")
        return g

    def _score_legend(self, s: Scored) -> Table:
        """What each radar axis measures, the raw value behind it, and which way is good.

        PTS are always 0..1 with 1 = best for the active profile; the arrow says which
        direction of the *raw* metric earns points.
        """
        p, prof = s.pool, self.profile
        g = Table(box=None, pad_edge=False, expand=True, header_style="bold #ffb000")
        g.add_column("AXIS", style="bold white", no_wrap=True)
        g.add_column("RAW", no_wrap=True)
        g.add_column("MEANING", style="grey70")

        def raw(arrow: str, value: str) -> Text:
            return Text.assemble((f"{arrow} ", "green"), (value, "#ffb000"))

        y = min(p.fee_yield_24h, p.fee_yield_7d_daily) if not p.is_new else p.fee_yield_24h * 0.5
        vol_cap = prof.max_volatility if prof.max_volatility < 1e6 else 100.0
        dd_cap = prof.max_drawdown if prof.max_drawdown < 1e6 else 100.0
        g.add_row(
            "yield",
            raw("▲", f"{y * 100:.2f}%/d"),
            f"daily fee ÷ TVL, lower of 24h and 7d avg. full at {prof.cap_yield * 100:.0f}%/d",
        )
        g.add_row(
            "turnover",
            raw("▲", f"{p.turnover_24h:.2f}x"),
            f"vol24 ÷ TVL, times the pool traded through. full at {prof.cap_turnover:.0f}x",
        )
        g.add_row(
            "consistency",
            raw("≈", f"{p.consistency:.2f}"),
            "fee24 ÷ (fee7d÷7). 0.7-1.5 steady, >1.5 spike, <0.7 fading, 7 = new",
        )
        g.add_row(
            "liveness",
            raw("▲", f"{p.liveness:.2f}"),
            "vol1h×24 ÷ vol24, trading right now? 1 = last hour on daily pace",
        )
        g.add_row(
            "depth",
            raw("▲", _usd(p.tvl)),
            f"TVL above profile floor {_usd(prof.min_tvl)}, log scale, full at 100×",
        )
        g.add_row(
            "risk",
            raw("▼", f"σ{p.volatility:.1f}% dd{p.drawdown24h:.1f}%"),
            f"price volatility + 24h drawdown vs caps {vol_cap:.0f}% / {dd_cap:.0f}%",
        )
        return g

    # ---- token metadata (logo + links) ----------------------------------
    def _token_infos(self, p: Pool) -> tuple[TokenInfo | None, TokenInfo | None]:
        return self.infos.get(p.token0_addr), self.infos.get(p.token1_addr)

    def _render_hero(self, s: Scored) -> None:
        p = s.pool
        i0, i1 = self._token_infos(p)
        t = Text()
        t.append(f"{p.pair}\n", style="bold white")
        for sym, info in ((p.token0, i0), (p.token1, i1)):
            name = info.name if info and info.name and info.name.upper() != sym.upper() else ""
            t.append(f"{sym}", style="bold #ffb000")
            if name:
                t.append(f"  {name}", style="dim")
            t.append("\n")
            links = info.links if info else []
            if links:
                for label, url in links:
                    t.append(f" {label} ", style=f"bold black on #ffb000 link {url}")
                    t.append(" ")
                t.append("\n")
            elif info is None:
                t.append("  …\n", style="dim")
            else:
                t.append("  no links\n", style="dim")
        self.main.query_one("#hero_text", Static).update(t)

    @work(thread=True, exclusive=True, group="enrich")
    def _enrich(self, p: Pool) -> None:
        addrs = [a for a in (p.token0_addr, p.token1_addr) if a]
        infos = self.meta.fetch(p.chain_id, addrs)
        logos: dict[str, Path | None] = {}
        for addr, fallback in ((p.token0_addr, p.token0_logo), (p.token1_addr, p.token1_logo)):
            if self.image_cls is None:
                break
            info = infos.get(addr)
            url = (info.image_url if info else "") or fallback
            logos[addr] = self.meta.logo_path(url)
        self.call_from_thread(self._apply_enrich, p, infos, logos)

    @work(thread=True, exclusive=True, group="enrich_flow")
    def _enrich_flow(self, rows: list[Scored]) -> None:
        """Swap counts for every row (DexScreener, batched, 90s cache)."""
        if not rows:
            return
        flows = self.flows.fetch(rows[0].pool.chain_id, [r.pool.address for r in rows])
        self.call_from_thread(self._apply_flow, rows, flows)

    def _apply_flow(self, rows: list[Scored], flows: dict[str, Flow]) -> None:
        try:
            table = self.main.query_one("#table", DataTable)
        except NoMatches:
            return
        changed = False
        for r in rows:
            f = flows.get(r.pool.address)
            if f is None or f is r.flow:
                continue
            changed = True
            r.flow = f
            key = r.pool.address + r.pool.protocol
            try:
                table.update_cell(key, "TX1H", _tx_cell(f, "h1"))
                table.update_cell(key, "TX24", _tx_cell(f, "h24"))
            except KeyError:
                continue
        if not changed:
            return
        if self.sort_col in ("TX1H", "TX24"):
            self._rebuild()
            return
        cur = self._selected()
        if cur is not None:
            self._render_detail(cur)

    @work(thread=True, exclusive=True, group="enrich_table")
    def _enrich_table(self, rows: list[Scored]) -> None:
        """Fetch link metadata for every token in the table (batched), then fill LINKS cells."""
        if not rows:
            return
        chain_id = rows[0].pool.chain_id
        addrs = sorted({a for r in rows for a in (r.pool.token0_addr, r.pool.token1_addr) if a})
        infos = self.meta.fetch(chain_id, addrs)
        self.call_from_thread(self._apply_enrich_table, rows, infos)

    def _apply_enrich_table(self, rows: list[Scored], infos: dict[str, TokenInfo]) -> None:
        self.infos_all.update(infos)
        try:
            table = self.main.query_one("#table", DataTable)
        except NoMatches:
            return  # app is shutting down
        changed = False
        for r in rows:
            n = len(self._pool_links(r.pool))
            changed |= n != r.n_links
            r.n_links = n
            key = r.pool.address + r.pool.protocol
            try:
                table.update_cell(key, "LINKS", self._links_cell(r.pool))
            except KeyError:
                continue  # table was rebuilt meanwhile
        if changed and self.sort_col == "LINKS":
            self._rebuild()

    def _apply_enrich(
        self, p: Pool, infos: dict[str, TokenInfo], logos: dict[str, Path | None]
    ) -> None:
        try:
            cur = self._selected()
        except NoMatches:
            return  # app is shutting down
        if cur is None or cur.pool.address != p.address:
            return  # selection moved on
        self.infos = infos
        for wid, addr in (("#logo0", p.token0_addr), ("#logo1", p.token1_addr)):
            if self.image_cls is None:
                break
            img = self.main.query_one(wid, self.image_cls)
            path = logos.get(addr)
            try:
                img.image = str(path) if path else None
            except (OSError, ValueError):  # corrupt / unsupported image bytes
                img.image = None
        self._render_hero(cur)

    # ---- events ---------------------------------------------------------
    def on_data_table_row_highlighted(self, ev: DataTable.RowHighlighted) -> None:
        if ev.cursor_row is not None and 0 <= ev.cursor_row < len(self.rows):
            s = self.rows[ev.cursor_row]
            # show cached meta immediately, else blank until the worker returns
            self.infos = {
                a: i
                for a in (s.pool.token0_addr, s.pool.token1_addr)
                if (i := self.meta.get(s.pool.chain_id, a))
            }
            self._render_detail(s)

    def on_input_changed(self, ev: Input.Changed) -> None:
        if ev.input.id == "find":
            self.find_text = ev.value.strip()
            self._rebuild()

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        if ev.input.id == "size":
            try:
                size = float(ev.value)
            except ValueError:
                size = 0.0
            if size > 0:
                self.position_size = size
                self._set_status(f"position size {size:,.0f}$")
            ev.input.remove_class("visible")
            self._rebuild()
        self.main.query_one("#table", DataTable).focus()

    def _selected(self) -> Scored | None:
        table = self.main.query_one("#table", DataTable)
        i = table.cursor_row
        return self.rows[i] if 0 <= i < len(self.rows) else None

    # ---- actions --------------------------------------------------------
    def action_profile(self, key: str) -> None:
        self.profile = PROFILES[key]
        self._rebuild()

    def action_toggle_quote(self) -> None:
        self.quote = None if self.quote else self.quote_default
        self._rebuild()

    def action_cycle_protocol(self) -> None:
        opts: list[str | None] = [None, *self.available_protocols]
        i = opts.index(self.protocol_filter) if self.protocol_filter in opts else 0
        self.protocol_filter = opts[(i + 1) % len(opts)]
        self._rebuild()

    def _set_sort(self, col: str) -> None:
        if col == self.sort_col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col = col
            self.sort_desc = col not in ASC_DEFAULT
        self._rebuild()

    def action_cycle_sort(self) -> None:
        i = SORT_ORDER.index(self.sort_col)
        col = SORT_ORDER[(i + 1) % len(SORT_ORDER)]
        self.sort_col = col
        self.sort_desc = col not in ASC_DEFAULT
        self._rebuild()

    def action_reverse_sort(self) -> None:
        self.sort_desc = not self.sort_desc
        self._rebuild()

    def on_data_table_header_selected(self, ev: DataTable.HeaderSelected) -> None:
        col = str(ev.column_key.value)
        if col in SORTABLE:
            self._set_sort(col)

    def action_positions(self) -> None:
        if not self.wallet:
            msg = f"add to .env: {api.WALLET_ENV}=0x… (or --wallet)"
            self._set_status(msg)
            self.notify(msg, title="POSITIONS NEEDS", severity="error", timeout=12)
            return
        self.push_screen(PositionsScreen(self), self._on_positions_closed)

    def _on_positions_closed(self, pool_key: str | None) -> None:
        """Jump the screener to the pool the user picked in the positions view."""
        if not pool_key:
            return
        self.find_text = pool_key
        box = self.main.query_one("#find", Input)
        box.value = pool_key
        box.add_class("visible")
        self._rebuild()
        if not self.rows:  # widen until the pool shows: any quote, then degen
            self.quote = None
            self._rebuild()
        if not self.rows:
            self.profile = PROFILES["degen"]
            self._rebuild()
        if not self.rows:
            self.call_after_refresh(
                self._set_status, f"pool {pool_key[:10]}… fails even the degen floor (tvl/vol)"
            )

    def pool_for(self, address: str, alt: str = "") -> Scored | None:
        """Screener view of a pool by address / v4 id (profile filters ignored)."""
        keys = {k for k in (address, alt) if k}
        for p in self.pools:
            if p.address in keys:
                sc = score_pool(p, self.profile)
                sc.sim = simulate(p, self.position_size)
                return sc
        return None

    def action_toggle_auto(self) -> None:
        self.auto = not self.auto
        if self.auto and self._timer is None:
            self._timer = self.set_interval(self.refresh_seconds, self._auto_tick)
        self._render_topbar()
        self._set_status(f"auto-refresh {'on' if self.auto else 'off'}")

    def action_toggle_watch(self) -> None:
        s = self._selected()
        if s is None:
            return
        on = self.store.toggle_watch(s.pool)
        self._set_status(f"{'★ watching' if on else '☆ unwatched'} {s.pool.pair}")
        self._rebuild()

    def action_watch_only(self) -> None:
        self.watch_only = not self.watch_only
        self._rebuild()

    def action_refresh(self) -> None:
        self._set_status("refreshing …")
        self._fetch()

    def action_open_url(self) -> None:
        s = self._selected()
        if s:
            webbrowser.open(s.pool.url)
            self._set_status(f"opened {s.pool.pair}")

    def action_links(self) -> None:
        s = self._selected()
        if s is None:
            return
        links = self._pool_links(s.pool)
        if not links:
            self._set_status(f"no social links for {s.pool.pair}")
            return
        self.push_screen(LinksModal(s.pool, links), self._on_link_chosen)

    def _on_link_chosen(self, url: str | None) -> None:
        if url:
            webbrowser.open(url)
            self._set_status(f"opened {url}")

    def on_data_table_row_selected(self, _: DataTable.RowSelected) -> None:
        self.action_links()

    def action_export_csv(self) -> None:
        if not self.rows:
            return
        out = Path("exports")
        out.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        path = out / f"{self.chain_id}_{self.profile.key}_{stamp}.csv"
        write_csv(path, self.rows)
        self._set_status(f"saved {path}")

    def action_find(self) -> None:
        box = self.main.query_one("#find", Input)
        box.add_class("visible")
        box.focus()

    def action_clear_find(self) -> None:
        box = self.main.query_one("#find", Input)
        box.value = ""
        box.remove_class("visible")
        self.main.query_one("#size", Input).remove_class("visible")
        self.find_text = ""
        self.main.query_one("#table", DataTable).focus()
        self._rebuild()

    def action_size(self) -> None:
        box = self.main.query_one("#size", Input)
        box.value = f"{self.position_size:.0f}"
        box.add_class("visible")
        box.focus()


def write_csv(path: Path, rows: list[Scored]) -> None:
    fields = [
        "rank",
        "score",
        "grade",
        "pair",
        "protocol",
        "chain",
        "fee_tier_pct",
        "tvl",
        "vol24",
        "fee24",
        "fee7d_daily",
        "yield24_pct",
        "yield7d_pct",
        "turnover",
        "consistency",
        "liveness",
        "volatility",
        "drawdown24",
        "apr24",
        "apr7d",
        "apr30d",
        "size",
        "my_fee_day",
        "my_share_pct",
        "il_day_est",
        "net_day",
        "lp_auto",
        "flags",
        "address",
        "url",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, s in enumerate(rows, 1):
            p = s.pool
            w.writerow(
                {
                    "rank": i,
                    "score": round(s.score, 1),
                    "grade": s.grade,
                    "pair": p.pair,
                    "protocol": p.protocol,
                    "chain": p.chain,
                    "fee_tier_pct": p.fee_tier_pct,
                    "tvl": round(p.tvl),
                    "vol24": round(p.s24h.volume),
                    "fee24": round(p.s24h.fee),
                    "fee7d_daily": round(p.s7d.fee / 7),
                    "yield24_pct": round(p.fee_yield_24h * 100, 3),
                    "yield7d_pct": round(p.fee_yield_7d_daily * 100, 3),
                    "turnover": round(p.turnover_24h, 2),
                    "consistency": round(p.consistency, 2),
                    "liveness": round(p.liveness, 2),
                    "volatility": round(p.volatility, 1),
                    "drawdown24": round(p.drawdown24h, 1),
                    "apr24": round(p.s24h.apr),
                    "apr7d": round(p.s7d.apr),
                    "apr30d": round(p.s30d.apr),
                    "size": round(s.sim.size) if s.sim else "",
                    "my_fee_day": round(s.sim.fee_day, 1) if s.sim else "",
                    "my_share_pct": round(s.sim.share * 100, 2) if s.sim else "",
                    "il_day_est": round(s.sim.il_day, 1) if s.sim else "",
                    "net_day": round(s.sim.net_day, 1) if s.sim else "",
                    "lp_auto": p.lp_auto,
                    "flags": " ".join(s.flags),
                    "address": p.address,
                    "url": p.url,
                }
            )
