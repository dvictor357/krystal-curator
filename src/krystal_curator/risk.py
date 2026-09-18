"""Realised σ / drawdown from local price snapshots, for feeds that report neither.

A chain feed gives a pool price per refresh but no volatility; Krystal gives `priceVolatility`
but its scale is only checked, never trusted blindly (`backtest --sigma`). Every refresh
records `Pool.price` into the sqlite `snapshots` table, so after enough history the same
variance-rate estimator the backtest uses can fill the blanks: `Pool.volatility` becomes
realised daily σ and `Pool.drawdown24h` the worst peak-to-trough move in the last 24 h.
Pools whose feed reported the numbers are left alone.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .backtest import realised_sigma

if TYPE_CHECKING:
    from .models import Pool
    from .store import Store

SIGMA_DAYS = 7.0  # history window for σ; the estimator needs ≥12 returns over ≥12 h
DD_HOURS = 24.0
DD_MIN_POINTS = 4
DD_MIN_SPAN_H = 6.0


def max_drawdown_pct(series: list[tuple], *, since: float) -> float | None:
    """Worst peak-to-trough move (negative percent) over samples at or after `since`.

    None when there are fewer than DD_MIN_POINTS priced samples or they span less than
    DD_MIN_SPAN_H hours: a two-point "drawdown" would just be noise.
    """
    pts = [(int(ts), float(p)) for ts, p, *_ in series if ts >= since and p and p > 0]
    if len(pts) < DD_MIN_POINTS or (pts[-1][0] - pts[0][0]) / 3600 < DD_MIN_SPAN_H:
        return None
    peak = pts[0][1]
    worst = 0.0
    for _, price in pts:
        peak = max(peak, price)
        worst = min(worst, price / peak - 1)
    return worst * 100


def fill_realised_risk(pools: list[Pool], store: Store, *, now: float | None = None) -> int:
    """Fill unknown volatility / drawdown from snapshot history in place.

    Returns how many pools received at least one value. A filled metric leaves
    `Pool.unknown`; `volatility_basis` records where σ came from so the UI can flag it.
    """
    wanted = [p for p in pools if p.unknown & {"volatility", "drawdown"}]
    if not wanted:
        return 0
    now = time.time() if now is None else now
    chains = {p.chain_id for p in wanted}
    series_by_key: dict[str, list[tuple]] = {}
    for chain_id in chains:
        series_by_key.update(store.price_series(chain_id, SIGMA_DAYS))
    dd_since = now - DD_HOURS * 3600
    filled = 0
    for p in wanted:
        series = series_by_key.get(f"{p.address}:{p.protocol}")
        if not series:
            continue
        known: set[str] = set()
        if "volatility" in p.unknown:
            row = realised_sigma(series)
            if row is not None:
                p.volatility = row.realised
                p.volatility_basis = f"realised over {row.span_h / 24:.1f}d / {row.n} returns"
                known.add("volatility")
        if "drawdown" in p.unknown:
            dd = max_drawdown_pct(series, since=dd_since)
            if dd is not None:
                p.drawdown24h = dd
                known.add("drawdown")
        if known:
            p.unknown = frozenset(p.unknown - known)
            filled += 1
    return filled
