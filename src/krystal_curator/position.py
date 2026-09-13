"""What a position of a given size would earn in a pool.

All estimates are first-order and assume the last 24h repeats:
- dilution: your fees = pool fees × size / (tvl + size)
- IL: full-range lognormal approximation, ≈ σ²/8 per day with σ the daily
  price volatility. A concentrated range multiplies fees *and* IL by roughly
  the same factor, so the fee/IL ratio is what matters when picking pools.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Pool


@dataclass(slots=True, frozen=True)
class Sim:
    size: float
    share: float  # fraction of pool after you enter
    fee_day: float  # USD/day, dilution adjusted (24h basis)
    fee_day_7d: float  # USD/day, dilution adjusted (7d-average basis)
    apr: float  # percent, on the 24h basis
    il_day_pct: float  # percent of position per day, full-range estimate
    il_day: float  # USD/day
    net_day: float  # fee_day - il_day
    fee_il_ratio: float  # fee_day / il_day; >1 fees outrun expected IL
    range_1s_7d: float  # ±% range that holds ~68% of 7-day outcomes
    range_2s_7d: float  # ±% range that holds ~95% of 7-day outcomes
    breakeven_days: float | None  # days for fees to cover one 2σ-7d move's IL

    @property
    def crowding(self) -> str:
        if self.share >= 0.5:
            return "YOU ARE THE POOL"
        if self.share >= 0.25:
            return "heavy"
        if self.share >= 0.10:
            return "notable"
        return "ok"


def il_fraction(move: float) -> float:
    """Impermanent loss for a price ratio move r (1.0 = unchanged), full range."""
    r = max(move, 1e-9)
    return 2 * math.sqrt(r) / (1 + r) - 1


def simulate(p: Pool, size: float) -> Sim:
    tvl_after = p.tvl + size
    share = size / tvl_after if tvl_after > 0 else 0.0
    fee_day = p.s24h.fee * share
    fee_day_7d = p.s7d.fee / 7 * share
    apr = fee_day * 365 / size * 100 if size > 0 else 0.0

    sigma = p.volatility / 100  # daily
    il_day_pct = sigma * sigma / 8 * 100
    il_day = size * il_day_pct / 100
    net_day = fee_day - il_day
    ratio = fee_day / il_day if il_day > 0 else math.inf

    s7 = sigma * math.sqrt(7)
    range_1s = s7 * 100
    range_2s = 2 * s7 * 100
    il_2s = -il_fraction(1 + 2 * s7) * size  # USD lost if price moves 2σ over 7d
    breakeven = il_2s / fee_day if fee_day > 0 else None

    return Sim(
        size=size,
        share=share,
        fee_day=fee_day,
        fee_day_7d=fee_day_7d,
        apr=apr,
        il_day_pct=il_day_pct,
        il_day=il_day,
        net_day=net_day,
        fee_il_ratio=ratio,
        range_1s_7d=range_1s,
        range_2s_7d=range_2s,
        breakeven_days=breakeven,
    )
