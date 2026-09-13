"""Telegram command interface, served by the `watch` daemon.

Only messages from the configured chat id are answered. State that commands change
(profile, size, muted) is kept in the sqlite kv table so it survives restarts.
"""

from __future__ import annotations

import html
import logging
from datetime import UTC, datetime
from pathlib import Path

from .advisor import advise
from .analytics import idle_capital, real_roi, report_markdown, track_record
from .autoconfig import recommend
from .config import Config
from .enrich import FlowCache, TokenMeta
from .models import CHAIN_SLUG, Pool
from .monitor import Monitor
from .notify import Telegram
from .position import simulate
from .positions import Position
from .profiles import PROFILE_ORDER, PROFILES
from .rotation import plan
from .scoring import Scored, curate, score_pool
from .store import Store

log = logging.getLogger("krystal.bot")

COMMANDS: list[tuple[str, str]] = [
    ("pos", "open positions + edges"),
    ("scan", "top pools: /scan [profile] [n]"),
    ("pool", "pool detail: /pool PAIR|address"),
    ("rotate", "rotation verdict per position"),
    ("setup", "Krystal Automation values per position"),
    ("watch", "star a pool: /watch PAIR"),
    ("unwatch", "unstar: /unwatch PAIR"),
    ("watchlist", "starred pools now"),
    ("size", "position size for sims: /size 50000"),
    ("profile", "risk profile: /profile balanced"),
    ("report", "send the vault report file"),
    ("status", "daemon heartbeat"),
    ("mute", "pause alerts: /mute [hours]"),
    ("unmute", "resume alerts"),
    ("help", "this list"),
]


def _usd(x: float) -> str:
    if abs(x) >= 1e6:
        return f"{x / 1e6:.2f}M"
    if abs(x) >= 1e3:
        return f"{x / 1e3:.1f}K"
    return f"{x:.0f}"


def _pre(text: str) -> str:
    return f"<pre>{html.escape(text)}</pre>"


class Bot:
    def __init__(self, tg: Telegram, store: Store, cfg: Config, mon: Monitor) -> None:
        self.tg = tg
        self.store = store
        self.cfg = cfg
        self.mon = mon
        self.offset: int | None = None
        self.meta = TokenMeta()
        self.flows = FlowCache()
        st = store.kv_get("bot.state") or {}
        self.profile = st.get("profile") or cfg.profile
        self.size = float(st.get("size") or cfg.size)
        self.muted_until = float(st.get("muted_until") or 0)
        tg.set_commands(COMMANDS)

    # ---- state ------------------------------------------------------------
    def _save(self) -> None:
        self.store.kv_set(
            "bot.state",
            {"profile": self.profile, "size": self.size, "muted_until": self.muted_until},
        )

    @property
    def muted(self) -> bool:
        return datetime.now(UTC).timestamp() < self.muted_until

    # ---- polling ------------------------------------------------------------
    def poll(self, timeout: int = 0) -> None:
        for upd in self.tg.get_updates(self.offset, timeout=timeout):
            self.offset = int(upd.get("update_id", 0)) + 1
            msg = upd.get("message") or {}
            chat = str((msg.get("chat") or {}).get("id"))
            text = (msg.get("text") or "").strip()
            if chat != str(self.tg.chat_id) or not text.startswith("/"):
                continue
            try:
                reply = self.handle(text)
            except Exception as e:
                log.exception("command failed: %s", text)
                reply = f"error: {e}"
            if reply:
                self.tg.send(reply, html=True)

    # ---- dispatch -----------------------------------------------------------
    def handle(self, text: str) -> str:
        parts = text.split()
        cmd = parts[0].lstrip("/").split("@")[0].lower()
        args = parts[1:]
        fn = getattr(self, f"cmd_{cmd}", None)
        if fn is None:
            return f"unknown command /{html.escape(cmd)} — /help"
        return fn(args)

    def _pools(self) -> list[Pool]:
        return self.mon.pools

    def _prof(self):
        return PROFILES[self.profile]

    def _find_pool(self, query: str) -> Scored | None:
        q = query.upper()
        for p in self._pools():
            if p.address.lower() == query.lower():
                return score_pool(p, self._prof())
        matches = [p for p in self._pools() if q in p.pair.upper()]
        if not matches:
            return None
        matches.sort(key=lambda p: p.s24h.fee, reverse=True)
        return score_pool(matches[0], self._prof())

    # ---- commands -----------------------------------------------------------
    def cmd_help(self, _: list[str]) -> str:
        lines = [f"/{c} — {d}" for c, d in COMMANDS]
        return "\n".join(lines) + f"\n\nprofile {self.profile} · size ${self.size:,.0f}"

    def cmd_status(self, _: list[str]) -> str:
        hb = self.store.kv_get("watch.heartbeat") or {}
        if not hb:
            return "no heartbeat yet"
        age = (datetime.now(UTC).timestamp() - float(hb.get("ts", 0))) / 60
        return (
            f"tick {age:.1f} min ago · pools {hb.get('pools')} · vaults {hb.get('vaults')} · "
            f"open {hb.get('open')} (OOR {hb.get('oor')}) · ticks {hb.get('ticks')}\n"
            f"profile {self.profile} · size ${self.size:,.0f} · alerts {'MUTED' if self.muted else 'on'}"
        )

    def cmd_profile(self, args: list[str]) -> str:
        if not args:
            return f"profile {self.profile}. options: {', '.join(PROFILE_ORDER)}"
        key = args[0].lower()
        if key not in PROFILES:
            return f"unknown profile. options: {', '.join(PROFILE_ORDER)}"
        self.profile = key
        self.mon.profile = PROFILES[key]
        self._save()
        return f"profile → {key}: {PROFILES[key].blurb}"

    def cmd_size(self, args: list[str]) -> str:
        if not args:
            return f"size ${self.size:,.0f}"
        try:
            v = float(args[0].replace("k", "000").replace("K", "000").replace(",", ""))
        except ValueError:
            return "usage: /size 50000"
        if v <= 0:
            return "size must be > 0"
        self.size = v
        self._save()
        return f"size → ${v:,.0f}"

    def cmd_mute(self, args: list[str]) -> str:
        hours = float(args[0]) if args else 8.0
        self.muted_until = datetime.now(UTC).timestamp() + hours * 3600
        self._save()
        return f"alerts muted for {hours:g}h"

    def cmd_unmute(self, _: list[str]) -> str:
        self.muted_until = 0
        self._save()
        return "alerts on"

    def cmd_scan(self, args: list[str]) -> str:
        prof = self._prof()
        n = 10
        for a in args:
            if a.lower() in PROFILES:
                prof = PROFILES[a.lower()]
            elif a.isdigit():
                n = max(1, min(30, int(a)))
        rows = curate(self._pools(), prof, quote=self.cfg.quote_or_none)[:n]
        if not rows:
            return f"no pool passes {prof.key}"
        flows = self.flows.fetch(self.cfg.chain, [r.pool.address for r in rows])
        out = [f"{prof.name}  quote {self.cfg.quote}  size ${self.size:,.0f}", ""]
        out.append(
            f"{'#':>2} {'PAIR':<15}{'RK':>2} {'Y24%':>5} {'MY$/D':>6} {'NET/D':>6} {'SHR':>4} {'TX24':>6}"
        )
        for i, r in enumerate(rows, 1):
            p = r.pool
            sim = simulate(p, self.size)
            f = flows.get(p.address)
            tx = f"{f.tx_h24:,}" if f and f.tx_h24 else "-"
            out.append(
                f"{i:>2} {p.pair[:15]:<15}{r.grade:>2} {p.fee_yield_24h * 100:>5.2f} "
                f"{_usd(sim.fee_day):>6} {_usd(sim.net_day):>6} {sim.share * 100:>3.0f}% {tx:>6}"
            )
        return _pre("\n".join(out)) + "\n/pool PAIR for detail"

    def cmd_pool(self, args: list[str]) -> str:
        if not args:
            return "usage: /pool PAIR or /pool 0xaddress"
        sc = self._find_pool(" ".join(args))
        if sc is None:
            return "no such pool in the current feed"
        p = sc.pool
        sim = simulate(p, self.size)
        f = self.flows.fetch(self.cfg.chain, [p.address]).get(p.address)
        infos = self.meta.fetch(p.chain_id, [a for a in (p.token0_addr, p.token1_addr) if a])
        links = []
        for addr in (p.token0_addr, p.token1_addr):
            info = infos.get(addr)
            if info:
                links += [f"{lab} {url}" for lab, url in info.links]
        body = [
            f"{p.pair} [{p.protocol}] tier {p.fee_tier_pct:.2f}%  grade {sc.grade}  score {sc.score:.0f} ({self.profile})",
            f"tvl {_usd(p.tvl)}  vol24 {_usd(p.s24h.volume)}  fee24 {_usd(p.s24h.fee)}",
            f"yield 24h {p.fee_yield_24h * 100:.2f}%/d  7d {p.fee_yield_7d_daily * 100:.2f}%/d",
            f"turnover {p.turnover_24h:.1f}x  cons {p.consistency:.2f}  live {p.liveness:.2f}",
            f"σ {p.volatility:.1f}%  dd24 {p.drawdown24h:.1f}%  flags {' '.join(sc.flags) or '-'}",
        ]
        if f and f.tx_h24:
            body.append(
                f"swaps 1h {f.tx_h1:,}  24h {f.tx_h24:,}  pace {f.pace:.1f}x  avg {f.avg_trade_h24:,.0f}$"
            )
        body += [
            "",
            f"${self.size:,.0f} here: share {sim.share * 100:.1f}% ({sim.crowding})",
            f"fee/d {sim.fee_day:,.0f}$  IL/d {sim.il_day:,.0f}$  net/d {sim.net_day:+,.0f}$",
            f"range 7d ±{sim.range_1s_7d:.1f}% (68%)  ±{sim.range_2s_7d:.1f}% (95%)",
        ]
        text = _pre("\n".join(body))
        text += f'\n<a href="{p.url}">open on Krystal</a>'
        if links:
            text += "\n" + "\n".join(html.escape(x) for x in links[:6])
        return text

    def _positions(self) -> list[Position]:
        return self.mon.open_positions()

    def cmd_pos(self, _: list[str]) -> str:
        opens = self._positions()
        vaults = self.mon.vaults
        if not vaults and not opens:
            return "no vaults / positions (wallet set?)"
        out = []
        for v in vaults:
            _idle, idle_pct = idle_capital(v)
            gain, _roi = real_roi(v)
            tr = track_record(v.closed)
            out.append(
                f"{v.name}: tvl {_usd(v.tvl)}$ pnl {v.pnl:+,.0f}$ 24h {v.earning_24h:+,.0f}$ "
                f"idle {idle_pct * 100:.0f}% since-start {gain:+,.0f}$ closed {tr.n} win {tr.win_rate * 100:.0f}%"
            )
        out.append("")
        for p in opens:
            adv = advise(p, self.mon.sigma_for(p), alert_sigma=self.cfg.alerts.edge_sigma)
            sc = self.mon.pool_for(p.pool_address, p.pool_alt)
            n = adv.nearest
            edge = (
                f"{n.name} edge {n.dist_pct:.1f}% ≈{n.sigmas:.1f}σ ~{n.days:.1f}d [{n.urgency}]"
                if n and n.sigmas is not None
                else "edge ?"
            )
            out.append(
                f"{'IN ' if p.in_range else 'OUT'} {p.pair} {p.value:,.0f}$ pnl {p.pnl:+,.0f}$ "
                f"fees {p.fees_total:,.1f}$ {p.age_days:.1f}d pool {sc.grade if sc else '?'}\n   {edge}"
            )
        return _pre("\n".join(out))

    def cmd_rotate(self, _: list[str]) -> str:
        opens = self._positions()
        if not opens:
            return "no open positions"
        out = []
        for p in opens:
            sc = self.mon.pool_for(p.pool_address, p.pool_alt)
            adv = advise(p, self.mon.sigma_for(p))
            rot = plan(
                p,
                adv.fee_per_day,
                self._pools(),
                self._prof(),
                quote=self.cfg.quote_or_none,
                current_pool=sc.pool if sc else None,
                top=3,
                cost_pct=self.cfg.rotate_cost_pct,
            )
            out.append(f"{p.pair} ({p.value:,.0f}$) net now {rot.current_net_day:+,.0f}$/d")
            out.append("  " + rot.verdict)
            for cd in rot.candidates:
                out.append(
                    f"  → {cd.pool.pair:<14} {cd.scored.grade} net {cd.sim.net_day:+,.0f}$/d "
                    f"share {cd.sim.share * 100:.0f}% payback {cd.payback_days:.1f}d"
                    if cd.payback_days is not None
                    else f"  → {cd.pool.pair:<14} {cd.scored.grade} net {cd.sim.net_day:+,.0f}$/d"
                )
        return _pre("\n".join(out)) + f"\nprofile {self.profile} — /profile to change"

    def cmd_setup(self, _: list[str]) -> str:
        opens = self._positions()
        if not opens:
            return "no open positions"
        out = []
        for p in opens:
            su = recommend(p, self.mon.sigma_for(p), self._prof())
            out.append(
                f"{p.vault or 'wallet'} {p.pair} {p.value:,.0f}$ — ±{su.range_pct:g}% / ~{su.hold_days:g}d"
            )
            for section, fs in su.by_section().items():
                out.append(f"[{section}]")
                out += [f"  {f.label}: {f.value}" for f in fs]
            out.append("")
        return _pre("\n".join(out))

    def cmd_watch(self, args: list[str]) -> str:
        if not args:
            return "usage: /watch PAIR"
        sc = self._find_pool(" ".join(args))
        if sc is None:
            return "no such pool"
        on = self.store.toggle_watch(sc.pool)
        if not on:  # toggled off by accident → toggle back
            self.store.toggle_watch(sc.pool)
        return f"★ watching {sc.pool.pair} [{sc.pool.protocol}]"

    def cmd_unwatch(self, args: list[str]) -> str:
        if not args:
            return "usage: /unwatch PAIR"
        sc = self._find_pool(" ".join(args))
        if sc is None or not self.store.is_watched(sc.pool):
            return "not watched"
        self.store.toggle_watch(sc.pool)
        return f"☆ unwatched {sc.pool.pair}"

    def cmd_watchlist(self, _: list[str]) -> str:
        rows = [p for p in self._pools() if self.store.is_watched(p)]
        if not rows:
            return "watchlist empty — /watch PAIR"
        out = [
            f"★ {p.pair:<15} tvl {_usd(p.tvl):>6} fee24 {_usd(p.s24h.fee):>6} y {p.fee_yield_24h * 100:.2f}% σ {p.volatility:.0f}%"
            for p in rows
        ]
        return _pre("\n".join(out))

    def cmd_report(self, _: list[str]) -> str:
        if not self.mon.vaults:
            return "no vaults"
        equity = {
            v.address: [h.tvl for h in self.store.vault_history(v.chain_id, v.address)]
            for v in self.mon.vaults
        }
        md = report_markdown(
            self.mon.vaults,
            chain=CHAIN_SLUG.get(self.cfg.chain, str(self.cfg.chain)),
            equity=equity,
        )
        out = Path("reports")
        out.mkdir(exist_ok=True)
        path = out / f"vaults_{self.cfg.chain}_{datetime.now(UTC):%Y%m%d_%H%M}.md"
        path.write_text(md, encoding="utf-8")
        self.tg.send_file(path, caption="vault report")
        return ""
