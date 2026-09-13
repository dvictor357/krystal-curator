"""Does the score predict forward fee yield? Evaluated on the local snapshot history.

For every snapshot time T that has a later snapshot near T + horizon, score each pool as
it looked at T and compare with the fee yield it actually delivered over the next 24h
(fee24 / tvl at T + horizon). No external data: this only needs the db the TUI / daemon fill.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from .models import Pool, Stat
from .positions import Position
from .profiles import RiskProfile
from .scoring import component_scores, passes, score_pool


@dataclass(slots=True)
class Sample:
    ts: int
    key: str
    score: float
    parts: dict[str, float]
    fwd_yield: float  # realised fee yield per day over the horizon
    fading: bool
    spike: bool


@dataclass(slots=True)
class Result:
    horizon_h: float
    pairs: int
    times: int
    spearman: float | None
    component_spearman: dict[str, float] = field(default_factory=dict)
    decile_yield: list[float] = field(default_factory=list)  # mean fwd yield, top→bottom
    fading_next_yield: float | None = None  # mean fwd yield of FADING pools
    steady_next_yield: float | None = None
    spike_next_yield: float | None = None


def _rank(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return num / (dx * dy) if dx and dy else None


def pool_from_row(r: tuple) -> Pool:
    _ts, chain_id, address, protocol, tvl, vol24, fee24, vol1h, fee1h, fee7d, apr24, vol, dd = r
    # vol7d is not stored: approximate from fees so is_new / consistency still work
    vol7d = vol24 * (fee7d / fee24) if fee24 and fee7d else vol24
    return Pool(
        chain_id=chain_id,
        protocol=protocol,
        address=address,
        token0="?",
        token1="?",
        fee_tier_pct=0.0,
        tvl=tvl or 0.0,
        s1h=Stat(volume=vol1h or 0.0, fee=fee1h or 0.0, apr=0.0),
        s24h=Stat(volume=vol24 or 0.0, fee=fee24 or 0.0, apr=apr24 or 0.0),
        s7d=Stat(volume=vol7d or 0.0, fee=fee7d or 0.0, apr=0.0),
        s30d=Stat(),
        drawdown24h=dd or 0.0,
        volatility=vol or 0.0,
        lp_auto=True,
        dynamic_fee=False,
        tag="",
    )


def build_samples(
    rows: list[tuple], prof: RiskProfile, *, horizon_h: float = 24, tol_h: float = 3
) -> list[Sample]:
    by_ts: dict[int, dict[str, tuple]] = defaultdict(dict)
    for r in rows:
        by_ts[r[0]][f"{r[2]}:{r[3]}"] = r
    times = sorted(by_ts)
    out: list[Sample] = []
    for t in times:
        target = t + horizon_h * 3600
        later = [u for u in times if abs(u - target) <= tol_h * 3600]
        if not later:
            continue
        u = min(later, key=lambda x: abs(x - target))
        for key, r in by_ts[t].items():
            r2 = by_ts[u].get(key)
            if r2 is None:
                continue
            p = pool_from_row(r)
            if passes(p, prof) is not None:
                continue
            p2 = pool_from_row(r2)
            fwd = (
                p2.fee_yield_24h * (24 / max(horizon_h, 1e-9))
                if horizon_h >= 24
                else p2.fee_yield_24h
            )
            sc = score_pool(p, prof)
            out.append(
                Sample(
                    ts=t,
                    key=key,
                    score=sc.score,
                    parts=component_scores(p, prof),
                    fwd_yield=fwd,
                    fading=0 < p.consistency < 0.7,
                    spike=p.consistency > 1.5,
                )
            )
    return out


def evaluate(rows: list[tuple], prof: RiskProfile, *, horizon_h: float = 24) -> Result:
    samples = build_samples(rows, prof, horizon_h=horizon_h)
    res = Result(
        horizon_h=horizon_h, pairs=len(samples), times=len({s.ts for s in samples}), spearman=None
    )
    if len(samples) < 10:
        return res
    scores = [s.score for s in samples]
    fwd = [s.fwd_yield for s in samples]
    res.spearman = spearman(scores, fwd)
    for k in samples[0].parts:
        res.component_spearman[k] = spearman([s.parts[k] for s in samples], fwd) or 0.0
    ordered = sorted(samples, key=lambda s: s.score, reverse=True)
    n = len(ordered)
    dec = max(1, n // 10)
    res.decile_yield = [
        statistics.mean(s.fwd_yield for s in ordered[i : i + dec]) for i in range(0, dec * 10, dec)
    ][:10]
    fading = [s.fwd_yield for s in samples if s.fading]
    spike = [s.fwd_yield for s in samples if s.spike]
    steady = [s.fwd_yield for s in samples if not s.fading and not s.spike]
    res.fading_next_yield = statistics.mean(fading) if fading else None
    res.spike_next_yield = statistics.mean(spike) if spike else None
    res.steady_next_yield = statistics.mean(steady) if steady else None
    return res


# ---- IL model check against realised vault trades ---------------------------


@dataclass(slots=True, frozen=True)
class ILCheck:
    n: int
    predicted_il: float  # sum of σ²/8 × days × deposit over closed trades
    realised_price_pnl: float  # sum of (pnl − fees): what price moves actually did
    fees: float


def il_check(closed: list[Position], sigma_by_pool: dict[str, float]) -> ILCheck:
    n = pred = price = fees = 0.0
    for p in closed:
        sig = sigma_by_pool.get(p.pool_address) or sigma_by_pool.get(p.pool_alt)
        if sig is None or p.deposit <= 0:
            continue
        n += 1
        pred += (sig / 100) ** 2 / 8 * p.age_days * p.deposit
        price += p.pnl - p.fees_total
        fees += p.fees_total
    return ILCheck(int(n), pred, price, fees)
