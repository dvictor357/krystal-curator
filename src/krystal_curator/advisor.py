"""Range-edge advisor for an open position: how far is price from each edge, in %,
in daily-σ units, and in expected days (random walk: σ·√t = distance ⇒ t = (d/σ)²)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .positions import Position

EDGE_ALERT_SIGMA = 0.5  # nearest edge closer than this many daily σ ⇒ alert


@dataclass(slots=True, frozen=True)
class Edge:
    name: str  # "lower" / "upper"
    price: float
    dist_pct: float  # % move from current price to reach it (positive)
    sigmas: float | None  # dist / daily σ
    days: float | None  # expected days for a random walk to travel that far

    @property
    def urgency(self) -> str:
        if self.sigmas is None:
            return "?"
        if self.sigmas < EDGE_ALERT_SIGMA:
            return "CRITICAL"
        if self.sigmas < 1.0:
            return "close"
        if self.sigmas < 2.0:
            return "watch"
        return "ok"


@dataclass(slots=True, frozen=True)
class Advice:
    lower: Edge | None
    upper: Edge | None
    width_pct: float  # half-width of the range vs geometric centre
    fee_per_day: float  # realised, USD
    fee_yield_day: float  # realised fees / value / age (fraction per day)
    hold_days: float

    @property
    def nearest(self) -> Edge | None:
        edges = [e for e in (self.lower, self.upper) if e and e.sigmas is not None]
        return min(edges, key=lambda e: e.sigmas or 0) if edges else None

    @property
    def alert(self) -> bool:
        n = self.nearest
        return n is not None and n.sigmas is not None and n.sigmas < EDGE_ALERT_SIGMA


def _edge(name: str, price: float, cur: float, sigma_pct: float | None) -> Edge:
    dist = abs(price - cur) / cur * 100 if cur > 0 else 0.0
    if sigma_pct and sigma_pct > 0:
        s = dist / sigma_pct
        return Edge(name, price, dist, s, s * s)
    return Edge(name, price, dist, None, None)


def advise(p: Position, sigma_daily_pct: float | None) -> Advice:
    cur = p.current_price
    lower = upper = None
    if cur and p.min_price > 0 and p.max_price > p.min_price:
        lower = _edge("lower", p.min_price, cur, sigma_daily_pct)
        upper = _edge("upper", p.max_price, cur, sigma_daily_pct)
    days = max(p.age_days, 1e-6)
    fees = p.fees_total
    return Advice(
        lower=lower,
        upper=upper,
        width_pct=p.range_width_pct,
        fee_per_day=fees / days,
        fee_yield_day=(fees / days / p.value) if p.value > 0 else 0.0,
        hold_days=p.age_days,
    )


def price_ladder(p: Position, width: int = 40) -> str:
    """`min ├────●──────┤ max` with ● at the current price (log scale)."""
    cur = p.current_price
    if not cur or p.min_price <= 0 or p.max_price <= p.min_price:
        return "range unknown"
    lo, hi = math.log(p.min_price), math.log(p.max_price)
    pos = (math.log(cur) - lo) / (hi - lo)
    inner = width - 2
    cells = ["─"] * inner
    i = int(pos * inner)
    if 0 <= i < inner:
        cells[i] = "●"
        return "├" + "".join(cells) + "┤"
    return ("●" if i < 0 else "├") + "".join(cells) + ("┤" if i < 0 else "●")
