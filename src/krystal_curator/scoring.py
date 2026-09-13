"""Filter + score pools against a RiskProfile."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import Pool
from .position import Sim
from .profiles import RiskProfile
from .store import Delta


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(slots=True)
class Scored:
    pool: Pool
    profile: RiskProfile
    score: float = 0.0
    parts: dict[str, float] = field(default_factory=dict)  # 0..1 per component
    grade: str = "?"
    flags: list[str] = field(default_factory=list)
    n_links: int = 0  # filled by the UI once token metadata is known
    sim: Sim | None = None  # position simulation for the chosen size
    watched: bool = False
    delta: Delta | None = None  # change vs ~24h-old local snapshot
    spark: str = ""  # fee24 sparkline from local snapshots

    @property
    def base(self) -> str:
        return self.pool.base_vs("USDG")


def passes(p: Pool, prof: RiskProfile) -> str | None:
    """None if the pool passes the profile's hard filters, else the reason."""
    if p.tvl < prof.min_tvl:
        return f"tvl < {prof.min_tvl:,.0f}"
    if p.s24h.volume < prof.min_vol24:
        return f"vol24 < {prof.min_vol24:,.0f}"
    if p.volatility > prof.max_volatility:
        return f"volatility {p.volatility:.0f} > {prof.max_volatility:.0f}"
    if abs(p.drawdown24h) > prof.max_drawdown:
        return f"drawdown {p.drawdown24h:.0f} > {prof.max_drawdown:.0f}"
    if p.fee_tier_pct > prof.max_fee_tier:
        return f"fee tier {p.fee_tier_pct:.2f}% > {prof.max_fee_tier:.2f}%"
    if p.is_new and not prof.allow_new:
        return "new pool (<1d history)"
    if prof.require_lp_auto and not p.lp_auto:
        return "no LP auto support"
    return None


def component_scores(p: Pool, prof: RiskProfile) -> dict[str, float]:
    """Each component in [0, 1]."""
    # Yield: use the *lower* of 24h and 7d-average so a one-day spike can't carry it.
    y = min(p.fee_yield_24h, p.fee_yield_7d_daily) if not p.is_new else p.fee_yield_24h * 0.5
    yield_pts = _clamp(math.sqrt(y / prof.cap_yield)) if prof.cap_yield > 0 else 0.0

    turnover_pts = _clamp(math.sqrt(p.turnover_24h / prof.cap_turnover))

    c = p.consistency
    if c <= 0:
        consistency_pts = 0.0
    elif c < 0.7:
        consistency_pts = c / 0.7  # fading
    elif c <= 1.5:
        consistency_pts = 1.0  # steady
    else:
        consistency_pts = 1.5 / c  # spike (new pools land at 7 → 0.21)

    liveness_pts = _clamp(p.liveness / 1.0)

    depth_pts = (
        _clamp(math.log10(p.tvl / prof.min_tvl) / 2) if p.tvl > 0 and prof.min_tvl > 0 else 0.0
    )

    vol_cap = prof.max_volatility if prof.max_volatility < 1e6 else 100.0
    dd_cap = prof.max_drawdown if prof.max_drawdown < 1e6 else 100.0
    risk_pts = 0.5 * (1 - _clamp(p.volatility / vol_cap)) + 0.5 * (
        1 - _clamp(abs(p.drawdown24h) / dd_cap)
    )

    return {
        "yield": yield_pts,
        "turnover": turnover_pts,
        "consistency": consistency_pts,
        "liveness": liveness_pts,
        "depth": depth_pts,
        "risk": risk_pts,
    }


def risk_grade(p: Pool) -> str:
    """Profile-independent A..E. Drives the RISK column."""
    pts = 0
    pts += 0 if p.volatility <= 10 else 1 if p.volatility <= 25 else 2 if p.volatility <= 50 else 3
    dd = abs(p.drawdown24h)
    pts += 0 if dd <= 10 else 1 if dd <= 25 else 2 if dd <= 50 else 3
    pts += 0 if p.tvl >= 1_000_000 else 1 if p.tvl >= 200_000 else 2
    pts += 2 if p.is_new else 0
    pts += 1 if p.fee_tier_pct >= 3 else 0
    return "ABCDE"[min(pts // 2, 4)]


def flags_for(p: Pool) -> list[str]:
    f: list[str] = []
    if p.tag:
        f.append(p.tag.upper())
    if p.is_new:
        f.append("NEW")
    if p.consistency > 2.5:
        f.append("SPIKE")
    if 0 < p.consistency < 0.4:
        f.append("FADING")
    if p.liveness == 0 and p.s24h.volume > 0:
        f.append("QUIET-1H")
    if p.dynamic_fee:
        f.append("DYN-FEE")
    if p.incentive_usd_day > 0:
        f.append("INCENTIVE")
    if not p.lp_auto:
        f.append("NO-AUTO")
    return f


def score_pool(p: Pool, prof: RiskProfile) -> Scored:
    parts = component_scores(p, prof)
    w = prof.weights
    total = sum(w.values()) or 1.0
    s = sum(parts[k] * w[k] for k in w) / total * 100
    return Scored(
        pool=p,
        profile=prof,
        score=s,
        parts=parts,
        grade=risk_grade(p),
        flags=flags_for(p),
    )


def curate(
    pools: list[Pool],
    prof: RiskProfile,
    *,
    quote: str | None = "USDG",
    protocols: set[str] | None = None,
) -> list[Scored]:
    """Apply universe filters (quote token, protocols), profile filters, then score+rank."""
    out: list[Scored] = []
    for p in pools:
        if quote and not p.has_token(quote):
            continue
        if protocols and p.protocol not in protocols:
            continue
        if passes(p, prof) is not None:
            continue
        out.append(score_pool(p, prof))
    out.sort(key=lambda s: s.score, reverse=True)
    return out
