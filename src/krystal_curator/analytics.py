"""Vault analytics: closed-position track record, idle capital, real ROI, markdown report."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .positions import Position
from .vaults import Vault


@dataclass(slots=True, frozen=True)
class Bucket:
    key: str
    n: int
    wins: int
    pnl: float
    fees: float
    avg_hold_days: float

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.pnl / self.n if self.n else 0.0


@dataclass(slots=True)
class TrackRecord:
    n: int = 0
    wins: int = 0
    pnl: float = 0.0
    fees: float = 0.0
    price_pnl: float = 0.0  # pnl − fees: what the price move did to you
    avg_pnl: float = 0.0
    median_pnl: float = 0.0
    avg_hold_days: float = 0.0
    avg_deposit: float = 0.0
    pnl_per_day: float = 0.0  # realised pnl per position-day
    best: Position | None = None
    worst: Position | None = None
    by_pair: list[Bucket] = field(default_factory=list)
    by_protocol: list[Bucket] = field(default_factory=list)
    by_tier: list[Bucket] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0


def _buckets(closed: list[Position], key) -> list[Bucket]:
    groups: dict[str, list[Position]] = defaultdict(list)
    for p in closed:
        groups[key(p)].append(p)
    out = [
        Bucket(
            k,
            len(ps),
            sum(1 for p in ps if p.pnl > 0),
            sum(p.pnl for p in ps),
            sum(p.fees_total for p in ps),
            sum(p.age_days for p in ps) / len(ps),
        )
        for k, ps in groups.items()
    ]
    return sorted(out, key=lambda b: b.pnl, reverse=True)


def track_record(closed: list[Position]) -> TrackRecord:
    if not closed:
        return TrackRecord()
    pnls = [p.pnl for p in closed]
    days = sum(p.age_days for p in closed)
    fees = sum(p.fees_total for p in closed)
    return TrackRecord(
        n=len(closed),
        wins=sum(1 for p in closed if p.pnl > 0),
        pnl=sum(pnls),
        fees=fees,
        price_pnl=sum(pnls) - fees,
        avg_pnl=statistics.mean(pnls),
        median_pnl=statistics.median(pnls),
        avg_hold_days=days / len(closed),
        avg_deposit=sum(p.deposit for p in closed) / len(closed),
        pnl_per_day=sum(pnls) / days if days > 0 else 0.0,
        best=max(closed, key=lambda p: p.pnl),
        worst=min(closed, key=lambda p: p.pnl),
        by_pair=_buckets(closed, lambda p: p.pair),
        by_protocol=_buckets(closed, lambda p: p.protocol),
        by_tier=_buckets(closed, lambda p: f"{p.fee_tier:.2f}%"),
    )


def idle_capital(v: Vault) -> tuple[float, float]:
    """(idle USD, idle fraction of TVL): vault value not deployed in open positions."""
    deployed = sum(p.value for p in v.positions)
    idle = max(0.0, v.tvl - deployed)
    return idle, (idle / v.tvl if v.tvl > 0 else 0.0)


def real_roi(v: Vault) -> tuple[float, float | None]:
    """(net USD gain since inception, ROI vs deposits) from deposits/withdrawals/value."""
    gain = v.my_value + v.my_withdrawn - v.my_deposit
    return gain, (gain / v.my_deposit if v.my_deposit > 0 else None)


# ---- markdown report -------------------------------------------------------


def _money(x: float) -> str:
    return f"{x:+,.0f}$" if x < 0 or x >= 1000 else f"{x:+,.2f}$"


def report_markdown(vaults: list[Vault], *, chain: str, equity: dict[str, list[float]]) -> str:
    """Investor-style report. `equity` maps vault address → recent TVL samples (may be empty)."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out = [f"# Vault report — {chain}", "", f"_generated {now}_", ""]
    for v in vaults:
        tr = track_record(v.closed)
        idle, idle_pct = idle_capital(v)
        gain, roi = real_roi(v)
        out += [
            f"## {v.name}  ({v.vault_type}, {'owned' if v.owned else 'joined'})",
            "",
            f"- Vault: `{v.address}` · [open on Krystal]({v.url})",
            f"- TVL **{v.tvl:,.0f}$** · idle {idle:,.0f}$ ({idle_pct * 100:.1f}%) · risk {v.risk} · age {v.age_days:.0f}d",
            f"- Earnings: 24h {_money(v.earning_24h)} · 30d {_money(v.earning_30d)} · APR {v.apr:.2f}% · lifetime fees {v.fee_generated:,.0f}$",
            f"- Unrealised PnL {_money(v.pnl)}",
            (
                f"- Since inception: deposited {v.my_deposit:,.0f}$, withdrawn {v.my_withdrawn:,.0f}$, "
                f"value {v.my_value:,.0f}$ → net {_money(gain)}"
                + (f" ({roi * 100:+.1f}%)" if roi is not None else "")
            ),
        ]
        samples = equity.get(v.address) or []
        if len(samples) >= 2:
            out.append(
                f"- TVL trend ({len(samples)} samples): {samples[0]:,.0f}$ → {samples[-1]:,.0f}$ "
                f"({(samples[-1] - samples[0]) / samples[0] * 100:+.1f}%)"
                if samples[0] > 0
                else ""
            )
        out += ["", "### Open positions", ""]
        if v.positions:
            out += [
                "| Pair | Protocol | Status | Value | Deposit | PnL | ROI | Fees | Pending | Age |",
                "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
            for p in sorted(v.positions, key=lambda x: x.value, reverse=True):
                out.append(
                    f"| {p.pair} | {p.protocol} | {p.status} | {p.value:,.0f}$ | {p.deposit:,.0f}$ | "
                    f"{_money(p.pnl)} | {p.roi_pct:+.2f}% | {p.fees_total:,.2f}$ | {p.fee_pending:,.2f}$ | {p.age_days:.1f}d |"
                )
        else:
            out.append("_none_")
        out += ["", "### Closed track record", ""]
        if tr.n:
            out.append(
                f"- {tr.n} closed · win rate **{tr.win_rate * 100:.0f}%** · realised PnL "
                f"**{_money(tr.pnl)}** (fees {tr.fees:,.0f}$, price {_money(tr.price_pnl)})"
            )
            out.append(
                f"- avg PnL {_money(tr.avg_pnl)} · median {_money(tr.median_pnl)} · avg hold "
                f"{tr.avg_hold_days:.1f}d · avg deposit {tr.avg_deposit:,.0f}$ · "
                f"{tr.pnl_per_day:+,.1f}$ per position-day"
            )
            if tr.best and tr.worst:
                out.append(
                    f"- best {tr.best.pair} {_money(tr.best.pnl)} · worst {tr.worst.pair} {_money(tr.worst.pnl)}"
                )
            out += [
                "",
                "| Pair | n | win | PnL | fees | avg hold |",
                "|---|---:|---:|---:|---:|---:|",
            ]
            for b in tr.by_pair:
                out.append(
                    f"| {b.key} | {b.n} | {b.win_rate * 100:.0f}% | {_money(b.pnl)} | {b.fees:,.0f}$ | {b.avg_hold_days:.1f}d |"
                )
        else:
            out.append("_no closed positions yet_")
        out.append("")
    return "\n".join(out)
