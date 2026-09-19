"""Rotation verdicts for the web: one row per open position, JSON-ready, no I/O."""

from __future__ import annotations

from .advisor import advise
from .models import Pool
from .positions import Position
from .profiles import RiskProfile
from .rotation import ROTATE_COST_PCT, plan
from .scoring import score_pool
from .vaults import Vault


def _pool_for(pools: list[Pool], address: str, alt: str = "") -> Pool | None:
    keys = {k for k in (address, alt) if k}
    return next((p for p in pools if p.address in keys), None)


def rotation_row(
    pos: Position,
    pools: list[Pool],
    profile: RiskProfile,
    *,
    quote: str | None,
    top: int = 5,
    cost_pct: float = ROTATE_COST_PCT,
) -> dict:
    current = _pool_for(pools, pos.pool_address, pos.pool_alt)
    sigma = current.volatility if current and "volatility" not in current.unknown else None
    adv = advise(pos, sigma)
    rot = plan(
        pos,
        adv.fee_per_day,
        pools,
        profile,
        quote=quote,
        current_pool=current,
        top=top,
        cost_pct=cost_pct,
    )
    grade = score_pool(current, profile).grade if current else None
    edge = adv.nearest
    best = rot.best
    return {
        "id": pos.id,
        "pair": pos.pair,
        "value": rot.value,
        "cost": rot.cost,
        "kind": rot.kind,
        "verdict": rot.verdict,
        "current": {
            "grade": grade,
            "address": pos.pool_address,
            "chain": pos.chain_id,
            "url": current.url if current else "",
            "poolId": (
                f"{current.chain_id}:{current.protocol}:{current.address.lower()}"
                if current
                else None
            ),
            "feeDay": adv.fee_per_day,
            "ilDay": rot.current_sim.il_day if rot.current_sim else None,
            "netDay": rot.current_net_day,
            "share": rot.current_sim.share if rot.current_sim else None,
            "sigmaKnown": sigma is not None,
            "inScreener": current is not None,
            "feesTotal": pos.fees_total,
            "ageDays": pos.age_days,
            "poolFee24": current.s24h.fee if current else None,
            "poolTvl": current.tvl if current else None,
        },
        "best": (
            {
                "pair": best.pool.pair,
                "poolId": f"{best.pool.chain_id}:{best.pool.protocol}:{best.pool.address.lower()}",
                "grade": best.scored.grade,
                "tvl": best.pool.tvl,
                "poolFee24": best.pool.s24h.fee,
                "spike": best.spike,
                "feeDay": best.fee_day,
                "ilDay": best.sim.il_day,
                "upliftDay": best.uplift_day,
                "paybackDays": best.payback_days,
            }
            if best
            else None
        ),
        "edge": (
            {
                "name": edge.name,
                "distPct": edge.dist_pct,
                "sigmas": edge.sigmas,
                "days": edge.days,
                "urgency": edge.urgency,
            }
            if edge
            else None
        ),
        "candidates": [
            {
                "pair": c.pool.pair,
                "poolId": f"{c.pool.chain_id}:{c.pool.protocol}:{c.pool.address.lower()}",
                "address": c.pool.address,
                "chain": c.pool.chain_id,
                "url": c.pool.url,
                "protocol": c.pool.protocol,
                "grade": c.scored.grade,
                "feeDay": c.fee_day,
                "feeDay24h": c.sim.fee_day,
                "feeDay7d": None if "stat7d" in c.pool.unknown else c.sim.fee_day_7d,
                "spike": c.spike,
                "ilDay": c.sim.il_day,
                "netDay": c.net_day,
                "share": c.sim.share,
                "upliftDay": c.uplift_day,
                "paybackDays": c.payback_days,
                "sigmaKnown": "volatility" not in c.pool.unknown,
            }
            for c in rot.candidates
        ],
    }


def rotation_rows(
    vaults: list[Vault],
    pools: list[Pool],
    profile: RiskProfile,
    *,
    quote: str | None,
    top: int = 5,
    cost_pct: float = ROTATE_COST_PCT,
) -> list[dict]:
    """Every open, funded position across the wallet's vaults."""
    return [
        rotation_row(p, pools, profile, quote=quote, top=top, cost_pct=cost_pct)
        for v in vaults
        for p in v.positions
        if p.status != "CLOSED" and p.value > 0
    ]
