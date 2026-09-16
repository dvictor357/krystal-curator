"""Does the score predict forward fee yield? Evaluated on the local snapshot history.

For every snapshot time T that has a later snapshot near T + horizon, score each pool as
it looked at T and compare with the fee yield it actually delivered over the next 24h
(fee24 / tvl at T + horizon). No external data: this only needs the db the TUI / daemon fill.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise

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


# ---- is `priceVolatility` a daily σ? -----------------------------------------
#
# Every money number downstream (σ²/8 IL, range ±σ√days, edge distance in σ, Automation
# range width) assumes the feed's priceVolatility is a one-day standard deviation in
# percent. This estimates the realised daily σ from the snapshot price history and reports
# the ratio realised / reported per pool. Ratio ≈ 1 → daily; ≈ 1/√7 (0.38) → the feed is a
# 7-day σ; ≈ 1/√30 (0.18) → 30-day; ≈ 1/√365 (0.05) → annualised.

SIGMA_MIN_RETURNS = 12
SIGMA_MIN_SPAN_H = 12.0


@dataclass(slots=True, frozen=True)
class SigmaRow:
    key: str
    n: int  # log returns used
    span_h: float
    stale_frac: float  # share of returns that were exactly 0 (feed price not refreshed)
    realised: float  # realised daily σ, percent
    reported: float  # latest priceVolatility in the window
    ratio: float | None  # realised / reported


@dataclass(slots=True)
class SigmaCheck:
    rows: list[SigmaRow] = field(default_factory=list)
    skipped: int = 0  # pools without enough priced history

    @property
    def median_ratio(self) -> float | None:
        rs = [r.ratio for r in self.rows if r.ratio is not None]
        return statistics.median(rs) if rs else None

    @property
    def verdict(self) -> str:
        m = self.median_ratio
        if m is None:
            return "not enough priced history yet"
        for scale, name in (
            (1.0, "daily"),
            (7**-0.5, "7-day"),
            (30**-0.5, "30-day"),
            (365**-0.5, "annualised"),
        ):
            if abs(m - scale) / scale <= 0.35:
                return f"reported σ looks {name} (median realised/reported = {m:.2f})"
        return f"no clean match (median realised/reported = {m:.2f}); treat σ math with care"


def realised_sigma(series: list[tuple]) -> SigmaRow | None:
    """Daily σ from irregularly spaced (ts, price, volatility) samples.

    Variance-rate estimator: Σ r² / Σ Δt scaled to a day, so mixed 5-min and 15-min gaps
    combine without bias. Consecutive equal prices are counted (stale_frac) because a feed
    that does not refresh between ticks pulls the estimate down.
    """
    pts = [(int(ts), float(p), float(v or 0.0)) for ts, p, v in series if p and p > 0]
    if len(pts) < 2:
        return None
    sum_r2 = sum_dt = 0.0
    n = zeros = 0
    for (t0, p0, _), (t1, p1, _) in pairwise(pts):
        dt = t1 - t0
        if dt <= 0:
            continue
        r = math.log(p1 / p0)
        sum_r2 += r * r
        sum_dt += dt
        n += 1
        zeros += r == 0.0
    span_h = (pts[-1][0] - pts[0][0]) / 3600
    if n < SIGMA_MIN_RETURNS or span_h < SIGMA_MIN_SPAN_H or sum_dt <= 0:
        return None
    realised = math.sqrt(sum_r2 / sum_dt * 86400) * 100
    reported = pts[-1][2]
    return SigmaRow(
        key="",
        n=n,
        span_h=span_h,
        stale_frac=zeros / n,
        realised=realised,
        reported=reported,
        ratio=realised / reported if reported > 0 else None,
    )


def sigma_check(series_by_key: dict[str, list[tuple]], *, min_reported: float = 0.5) -> SigmaCheck:
    """Realised vs reported σ per pool; pools whose reported σ < min_reported are ignored
    (dead pools make the ratio meaningless)."""
    out = SigmaCheck()
    for key, series in series_by_key.items():
        row = realised_sigma(series)
        if row is None or row.reported < min_reported:
            out.skipped += 1
            continue
        out.rows.append(
            SigmaRow(key=key, **{f: getattr(row, f) for f in row.__slots__ if f != "key"})
        )
    out.rows.sort(key=lambda r: r.n, reverse=True)
    return out
