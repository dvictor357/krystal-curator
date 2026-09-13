"""Shared monitoring core used by the TUI and the headless `watch` daemon.

One `Monitor.tick(pools, vaults)` per refresh: persists snapshots, evaluates the alert
rules against the previous tick, returns the alerts to deliver.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .advisor import advise
from .analytics import idle_capital
from .models import Pool
from .positions import Position
from .profiles import PROFILES, RiskProfile
from .scoring import Scored, score_pool
from .store import Store
from .vaults import Vault

SNAPSHOT_EVERY = 15 * 60  # seconds between full-universe pool snapshots
VAULT_SNAPSHOT_EVERY = 5 * 60  # seconds between vault equity snapshots
POS_PNL_DROP = 0.05  # alert when a position's PnL falls by this fraction of its value
WATCH_TVL_MOVE = 30  # % TVL move in an hour on a starred pool
WATCH_FEE_DROP = -50  # % fee24 change on a starred pool
WATCH_DRAWDOWN = -30  # % drawdown on a starred pool


@dataclass(slots=True, frozen=True)
class Alert:
    title: str
    text: str
    severity: str  # information / warning / error


@dataclass(slots=True)
class Monitor:
    store: Store
    profile: RiskProfile = field(default_factory=lambda: PROFILES["balanced"])
    pools: list[Pool] = field(default_factory=list)
    vaults: list[Vault] = field(default_factory=list)
    direct: list[Position] = field(default_factory=list)
    pos_state: dict[str, dict] = field(default_factory=dict)

    # ---- lookups --------------------------------------------------------
    def pool_for(self, address: str, alt: str = "") -> Scored | None:
        keys = {k for k in (address, alt) if k}
        for p in self.pools:
            if p.address in keys:
                return score_pool(p, self.profile)
        return None

    def open_positions(self) -> list[Position]:
        return [p for v in self.vaults for p in v.positions] + list(self.direct)

    def sigma_for(self, p: Position) -> float | None:
        sc = self.pool_for(p.pool_address, p.pool_alt)
        return sc.pool.volatility if sc else None

    # ---- tick -----------------------------------------------------------
    def tick(self, pools: list[Pool], vaults: list[Vault] | None) -> list[Alert]:
        self.pools = pools
        self.store.mark_seen(pools)
        alerts = self._watchlist_alerts(pools)
        self._snapshot_pools(pools)
        if vaults is not None:
            self.vaults = vaults
            alerts += self._position_alerts()
            self._snapshot_vaults()
        return alerts

    # ---- pools ----------------------------------------------------------
    def _watchlist_alerts(self, pools: list[Pool]) -> list[Alert]:
        out: list[Alert] = []
        for p in pools:
            if not self.store.is_watched(p):
                continue
            d = self.store.delta(p, hours=1)
            msgs = []
            if d.tvl_pct is not None and abs(d.tvl_pct) >= WATCH_TVL_MOVE:
                msgs.append(f"TVL {d.tvl_pct:+.0f}%")
            if d.fee24_pct is not None and d.fee24_pct <= WATCH_FEE_DROP:
                msgs.append(f"fee24 {d.fee24_pct:+.0f}%")
            if p.drawdown24h <= WATCH_DRAWDOWN:
                msgs.append(f"drawdown {p.drawdown24h:.0f}%")
            if msgs:
                out.append(Alert("WATCH ALERT", f"★ {p.pair}: {', '.join(msgs)}", "warning"))
        return out

    def _snapshot_pools(self, pools: list[Pool]) -> None:
        """Starred pools every tick; the wider universe (aggressive floor) every 15 min."""
        floor = PROFILES["aggressive"]
        full = time.time() - self.store.last_ts() >= SNAPSHOT_EVERY
        keep = [
            p
            for p in pools
            if self.store.is_watched(p)
            or (full and p.tvl >= floor.min_tvl and p.s24h.volume >= floor.min_vol24)
        ]
        self.store.record(keep)
        self.store.prune(14)

    # ---- positions ------------------------------------------------------
    def _position_alerts(self) -> list[Alert]:
        """State changes since the previous tick; the first tick only reports what is
        bad right now (out of range, edge critical)."""
        out: list[Alert] = []
        first = not self.pos_state
        for p in self.open_positions():
            sc = self.pool_for(p.pool_address, p.pool_alt)
            grade = sc.grade if sc else "?"
            adv = advise(p, self.sigma_for(p))
            prev = self.pos_state.get(p.id)
            label = f"{p.vault or 'wallet'} {p.pair}"
            if not p.in_range and (first or (prev and prev["in_range"])):
                out.append(Alert("POSITION", f"{label} OUT OF RANGE ({p.value:,.0f}$)", "error"))
            elif p.in_range and prev and not prev["in_range"]:
                out.append(Alert("POSITION", f"{label} back in range", "information"))
            n = adv.nearest
            if adv.alert and n and (first or not (prev and prev["edge_alert"])):
                out.append(
                    Alert(
                        "EDGE",
                        f"{label}: {n.name} edge {n.dist_pct:.1f}% away ≈ {n.sigmas:.1f}σ (~{n.days:.1f}d)",
                        "warning",
                    )
                )
            if prev and grade != "?" and prev["grade"] != "?" and grade > prev["grade"]:
                out.append(
                    Alert("POOL DECAY", f"{label}: pool grade {prev['grade']} → {grade}", "warning")
                )
            if prev and p.value > 0 and (prev["pnl"] - p.pnl) / p.value >= POS_PNL_DROP:
                out.append(
                    Alert(
                        "PNL DROP", f"{label}: PnL {prev['pnl']:+,.0f}$ → {p.pnl:+,.0f}$", "warning"
                    )
                )
            self.pos_state[p.id] = {
                "in_range": p.in_range,
                "grade": grade,
                "pnl": p.pnl,
                "edge_alert": adv.alert,
            }
        return out

    def _snapshot_vaults(self) -> None:
        if time.time() - self.store.last_vault_ts() < VAULT_SNAPSHOT_EVERY:
            return
        rows = []
        for v in self.vaults:
            idle, _ = idle_capital(v)
            rows.append(
                (
                    v.chain_id,
                    v.address,
                    v.tvl,
                    v.pnl,
                    v.earning_24h,
                    v.my_value,
                    idle,
                    len(v.positions),
                )
            )
        if rows:
            self.store.record_vaults(rows)
