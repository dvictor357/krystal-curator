"""Terminal UI. Bloomberg-ish: dense table, amber chrome, single-key commands."""

from __future__ import annotations

import csv
import os
import warnings
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

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
from .enrich import TokenInfo, TokenMeta
from .models import Pool
from .profiles import PROFILES, RiskProfile
from .scoring import Scored, curate

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


COLUMNS = (
    "#",
    "PAIR",
    "PROTO",
    "TIER%",
    "TVL",
    "VOL24",
    "FEE24",
    "FEE/D 7D",
    "Y24%",
    "Y7D%",
    "V/TVL",
    "CONS",
    "LIVE",
    "σ%",
    "DD24",
    "APR7D",
    "SCORE",
    "RK",
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
    "FEE/D 7D": lambda s: s.pool.s7d.fee / 7,
    "Y24%": lambda s: s.pool.fee_yield_24h,
    "Y7D%": lambda s: s.pool.fee_yield_7d_daily,
    "V/TVL": lambda s: s.pool.turnover_24h,
    "CONS": lambda s: s.pool.consistency,
    "LIVE": lambda s: s.pool.liveness,
    "σ%": lambda s: s.pool.volatility,
    "DD24": lambda s: s.pool.drawdown24h,
    "APR7D": lambda s: s.pool.s7d.apr,
    "SCORE": lambda s: s.score,
    "RK": lambda s: s.grade,
    "LINKS": lambda s: s.n_links,
}
SORT_ORDER = [c for c in COLUMNS if c in SORTABLE]
# text columns and risk columns read naturally ascending
ASC_DEFAULT = {"PAIR", "PROTO", "σ%", "RK"}


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
        Binding("o", "open_url", "OPEN"),
        Binding("l", "links", "LINKS"),
        Binding("e", "export_csv", "CSV"),
        Binding("slash", "find", "FIND", key_display="/"),
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
    ) -> None:
        super().__init__()
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

    # ---- data -----------------------------------------------------------
    @work(thread=True, exclusive=True, group="fetch")
    def _fetch(self) -> None:
        try:
            pools = api.fetch_pools(self.chain_id)
        except api.KrystalError as e:
            self.call_from_thread(self._set_status, f"ERROR {e}")
            return
        self.call_from_thread(self._on_pools, pools)

    def _on_pools(self, pools: list[Pool]) -> None:
        self.pools = pools
        self.last_refresh = datetime.now(UTC)
        if not self.available_protocols:
            self.available_protocols = sorted({p.protocol for p in pools})
        self._rebuild()

    def _current_rows(self) -> list[Scored]:
        protos = {self.protocol_filter} if self.protocol_filter else None
        rows = curate(self.pools, self.profile, quote=self.quote, protocols=protos)
        if self.find_text:
            ft = self.find_text.upper()
            rows = [r for r in rows if ft in r.pool.pair.upper() or ft in r.pool.address]
        for r in rows:
            r.n_links = len(self._pool_links(r.pool))
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
        self.rows = self._current_rows()
        table = self.main.query_one("#table", DataTable)
        table.clear(columns=True)
        for label, name in zip(self._column_labels(), COLUMNS, strict=True):
            table.add_column(label, key=name)
        for i, s in enumerate(self.rows, 1):
            p = s.pool
            table.add_row(
                Text(str(i), justify="right", style="dim"),
                Text(p.pair, style="bold white"),
                Text(p.protocol, style="cyan"),
                Text(_pct(p.fee_tier_pct), justify="right"),
                Text(_usd(p.tvl), justify="right"),
                Text(_usd(p.s24h.volume), justify="right"),
                Text(_usd(p.s24h.fee), justify="right", style="bold yellow"),
                Text(_usd(p.s7d.fee / 7), justify="right"),
                _color_num(_pct(p.fee_yield_24h * 100), p.fee_yield_24h, 0.01, 0.0005),
                _color_num(_pct(p.fee_yield_7d_daily * 100), p.fee_yield_7d_daily, 0.01, 0.0005),
                _color_num(_pct(p.turnover_24h, 1), p.turnover_24h, 2, 0.3),
                _color_num(_pct(p.consistency), p.consistency, 0.7, 0.0)
                if p.consistency <= 1.5
                else Text(_pct(p.consistency), style="bold red", justify="right"),
                _color_num(_pct(p.liveness), p.liveness, 0.8, 0.2),
                _color_num(_pct(p.volatility, 1), p.volatility, 10, 40, invert=True),
                _color_num(_pct(p.drawdown24h, 1), abs(p.drawdown24h), 10, 40, invert=True),
                Text(_pct(p.s7d.apr, 0), justify="right"),
                Text(f"{s.score:5.1f}", justify="right", style="bold #ffb000"),
                _grade_text(s.grade),
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
        if self.rows:
            table.move_cursor(row=0)
            self._render_detail(self.rows[0])
        else:
            self.main.query_one("#detail", Static).update(
                Text(
                    "no pool passes this profile — try 3/4 or press u to widen quote",
                    style="red",
                )
            )

    # ---- rendering ------------------------------------------------------
    def _render_topbar(self) -> None:
        ts = self.last_refresh.strftime("%H:%M:%S UTC") if self.last_refresh else "--:--:--"
        chain = next((p.chain for p in self.pools[:1]), str(self.chain_id)).upper()
        proto = (self.protocol_filter or "ALL").upper()
        quote = self.quote or "ANY"
        cloud = "  CLOUD:ON" if self.cloud_key else ""
        img = f"  IMG:{self.image_mode.upper()}"
        self.main.query_one("#topbar", Static).update(
            f" KRYSTAL CURATOR   {chain}({self.chain_id})   QUOTE:{quote}   PROTO:{proto}   "
            f"PROFILE:{self.profile.name}   {ts}{cloud}{img}"
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
        auto = "yes" if p.lp_auto else "NO"
        dyn = "dynamic" if p.dynamic_fee else "fixed"
        t.add_row(
            "MISC",
            f"lp-auto {auto}   fee {dyn}   incentives {p.incentive_usd_day:,.0f}$/d",
        )
        if p.tx24 is not None:
            t.add_row("TX24", f"{p.tx24:,}")
        t.add_row("", "")

        b = Table(box=None, pad_edge=False, expand=True, header_style="bold #ffb000")
        b.add_column("SCORE")
        b.add_column("W", justify="right")
        b.add_column("PTS", justify="right")
        b.add_column("")
        for k, wt in self.profile.weights.items():
            pts = s.parts.get(k, 0.0)
            bar = "█" * int(pts * 20) + "░" * (20 - int(pts * 20))
            b.add_row(k, f"{wt:.0f}", f"{pts:.2f}", Text(bar, style="#ffb000"))
        b.add_row(
            Text("TOTAL", style="bold"),
            "",
            Text(f"{s.score:.1f}", style="bold white"),
            "",
        )
        t.add_row(self.profile.name, b)
        self.main.query_one("#detail_body", Static).update(t)
        self._render_hero(s)
        self._enrich(p)

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
        self.find_text = ev.value.strip()
        self._rebuild()

    def on_input_submitted(self, _: Input.Submitted) -> None:
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
        self.find_text = ""
        self.main.query_one("#table", DataTable).focus()
        self._rebuild()


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
                    "lp_auto": p.lp_auto,
                    "flags": " ".join(s.flags),
                    "address": p.address,
                    "url": p.url,
                }
            )
