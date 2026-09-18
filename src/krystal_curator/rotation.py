"""Opportunity cost: what the same dollars would earn in the screener's best pools."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Pool
from .position import Sim, simulate
from .positions import Position
from .profiles import RiskProfile
from .scoring import Scored, curate

ROTATE_COST_PCT = 0.3  # % of value burned by exiting + re-entering (swaps, slippage, gas)
MIN_UPLIFT_DAY = 0.05  # USD/day below which a "better" pool is noise, not a rotation
MIN_ROTATE_VALUE = 10.0  # USD; below this the switch cost and dust dominate, no verdict
SPIKE_RATIO = 2.0  # 24h fee/day more than this × the 7d average = a spike, not a yield


@dataclass(slots=True, frozen=True)
class Candidate:
    scored: Scored
    sim: Sim
    fee_day: float  # conservative fee basis: min(24h, 7d average) when 7d is known
    net_day: float  # fee_day − IL/day; what uplift and ranking use
    spike: bool  # 24h fees run far above the 7d average: yesterday, not a yield
    uplift_day: float  # candidate net/day − current net/day (USD)
    payback_days: float | None  # rotation cost / uplift; None if no uplift

    @property
    def pool(self) -> Pool:
        return self.scored.pool


def conservative(sim: Sim, pool: Pool) -> tuple[float, bool]:
    """Fee/day to plan on, and whether the 24h number is a spike over the 7d average."""
    if "stat7d" in pool.unknown or sim.fee_day_7d <= 0:
        return sim.fee_day, False
    return min(sim.fee_day, sim.fee_day_7d), sim.fee_day > SPIKE_RATIO * sim.fee_day_7d


@dataclass(slots=True, frozen=True)
class Rotation:
    value: float
    current_net_day: float  # realised fees/day − IL estimate for the current pool
    current_sim: Sim | None  # pool-average expectation for the same $ in the current pool
    cost: float  # USD to rotate
    candidates: list[Candidate]

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def kind(self) -> str:
        """Machine form of `verdict`: rotate / consider / stay / none."""
        b = self.best
        if b is None or self.value < MIN_ROTATE_VALUE:
            return "none"
        if b.uplift_day < MIN_UPLIFT_DAY or b.payback_days is None:
            return "stay"
        if b.payback_days <= 3:
            return "rotate"
        if b.payback_days <= 14:
            return "consider"
        return "stay"

    @property
    def verdict(self) -> str:
        b = self.best
        if b is None:
            return "no candidate passes the profile"
        if self.value < MIN_ROTATE_VALUE:
            return f"too small to rotate ({self.value:,.2f}$)"
        if b.uplift_day < MIN_UPLIFT_DAY:
            return "STAY — nothing in this profile beats the current position"
        if b.payback_days is not None and b.payback_days <= 3:
            pb = "<0.1d" if b.payback_days < 0.1 else f"{b.payback_days:.1f}d"
            return f"ROTATE → {b.pool.pair}: +{b.uplift_day:,.0f}$/d, cost paid back in {pb}"
        if b.payback_days is not None and b.payback_days <= 14:
            return f"CONSIDER {b.pool.pair}: +{b.uplift_day:,.0f}$/d, payback {b.payback_days:.1f}d"
        return f"STAY — best uplift +{b.uplift_day:,.0f}$/d needs {b.payback_days:.0f}d to pay the switch"


def plan(
    pos: Position,
    realised_fee_day: float,
    pools: list[Pool],
    profile: RiskProfile,
    *,
    quote: str | None,
    current_pool: Pool | None,
    top: int = 8,
    cost_pct: float = ROTATE_COST_PCT,
) -> Rotation:
    value = pos.value
    cost = value * cost_pct / 100
    cur_sim = simulate(current_pool, value) if current_pool else None
    current_net = realised_fee_day - (cur_sim.il_day if cur_sim else 0.0)

    cands: list[Candidate] = []
    for sc in curate(pools, profile, quote=quote):
        if current_pool and sc.pool.address == current_pool.address:
            continue
        sim = simulate(sc.pool, value)
        sc.sim = sim
        fee_day, spike = conservative(sim, sc.pool)
        net_day = fee_day - sim.il_day
        uplift = net_day - current_net
        payback = cost / uplift if uplift > 0 else None
        cands.append(Candidate(sc, sim, fee_day, net_day, spike, uplift, payback))
    cands.sort(key=lambda c: c.net_day, reverse=True)
    return Rotation(value, current_net, cur_sim, cost, cands[:top])
