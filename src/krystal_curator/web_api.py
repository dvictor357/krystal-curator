"""Private HTTP bridge for Curator web; run behind the Next.js server, never publicly."""

from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from starlette.concurrency import run_in_threadpool
from tortoise.contrib.fastapi import RegisterTortoise

from . import api, leaderboard, vaults, web_alerts, web_rotation, web_verdicts
from .models import CHAIN_SLUG, Pool
from .position import simulate
from .profiles import PROFILES
from .scoring import curate
from .web_auth import authorize, market_user, router
from .web_cache import Cache, Meta
from .web_db import TORTOISE_ORM, User

store = Cache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(app, config=TORTOISE_ORM):
        task = asyncio.create_task(web_alerts.loop(store))
        try:
            yield
        finally:
            task.cancel()


app = FastAPI(title="Curator analytics", dependencies=[Depends(authorize)], lifespan=lifespan)
app.include_router(router)


Fresh = Annotated[bool, Query(description="Bypass the cache once (manual refresh)")]


def chain_check(chain: int, source: str = "krystal"):
    if chain not in CHAIN_SLUG or source != "krystal":
        raise HTTPException(422, "Unsupported chain for this source.")


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [finite(v) for v in value]
    return value


def pool_rows(pools: list[Pool], profile: str, quote: str, size: float):
    rows = []
    for scored in curate(pools, PROFILES[profile], quote=quote or None):
        p = scored.pool
        sim = asdict(simulate(p, size))
        if "volatility" in p.unknown:
            for key in (
                "il_day_pct",
                "il_day",
                "net_day",
                "fee_il_ratio",
                "range_1s_7d",
                "range_2s_7d",
                "breakeven_days",
            ):
                sim[key] = None
        if "stat7d" in p.unknown:
            sim["fee_day_7d"] = None
        rows.append(
            {
                "id": f"{p.chain_id}:{p.protocol}:{p.address.lower()}",
                "pair": p.pair,
                "token0": p.token0,
                "token1": p.token1,
                "feeTier": p.fee_tier_pct,
                "token0Address": p.token0_addr,
                "token1Address": p.token1_addr,
                "token0Logo": p.token0_logo if p.token0_logo.startswith("https://") else "",
                "token1Logo": p.token1_logo if p.token1_logo.startswith("https://") else "",
                "address": p.address,
                "chain": p.chain_id,
                "protocol": p.protocol,
                "source": p.source,
                "url": p.url,
                "tvl": p.tvl,
                "volume": p.s24h.volume,
                "fees": p.s24h.fee,
                "feeYield": p.fee_yield_24h * 100,
                "volatility": None if "volatility" in p.unknown else p.volatility,
                "drawdown": None if "drawdown" in p.unknown else p.drawdown24h,
                "score": scored.score,
                "grade": scored.grade,
                "flags": scored.flags,
                "parts": scored.parts,
                "unknown": list(p.unknown),
                "risks": p.risks,
                "tvlBasis": p.tvl_basis,
                "sim": sim,
            }
        )
    return finite(rows)


@app.get("/pools", dependencies=[Depends(market_user)])
def pools(
    chain: int = 4663,
    source: Literal["krystal"] = "krystal",
    profile: Literal["conservative", "balanced", "aggressive", "degen"] = "balanced",
    quote: Annotated[str, Query(max_length=20, pattern=r"^[A-Za-z0-9]*$")] = "USDG",
    size: Annotated[float, Query(ge=1, le=100_000_000, allow_inf_nan=False)] = 10000,
    fresh: Fresh = False,
    response: Response = None,
):
    chain_check(chain, source)
    entry, meta = store.get(
        ("pools", chain, source), lambda: api.fetch_pools(chain, source=source), fresh=fresh
    )
    meta.apply(response, 60)
    return {
        "rows": pool_rows(entry.value, profile, quote, size),
        "fetchedAt": entry.at,
        "source": source,
        "demo": False,
    }


@app.get("/positions", dependencies=[Depends(market_user)])
def positions(
    wallet: Annotated[str, Query(pattern=r"^0x[a-fA-F0-9]{40}$")],
    chain: int = 4663,
    fresh: Fresh = False,
    response: Response = None,
):
    chain_check(chain)
    entry, meta = store.get(
        ("positions", chain, wallet.lower()),
        lambda: vaults.fetch_vaults(wallet, chain_id=chain),
        fresh=fresh,
    )
    meta.apply(response, 60)
    return {
        "rows": finite([asdict(v) | {"url": v.url} for v in entry.value]),
        "fetchedAt": entry.at,
    }


@app.get("/rotations")
async def rotations(
    wallet: Annotated[str, Query(pattern=r"^0x[a-fA-F0-9]{40}$")],
    user: Annotated[User, Depends(market_user)],
    chain: int = 4663,
    source: Literal["krystal"] = "krystal",
    profile: Literal["conservative", "balanced", "aggressive", "degen"] = "balanced",
    quote: Annotated[str, Query(max_length=20, pattern=r"^[A-Za-z0-9]*$")] = "USDG",
    fresh: Fresh = False,
    response: Response = None,
):
    """Opportunity cost per open position: same dollars in the profile's best pools.

    Every verdict shown is logged so the position can later carry its own track record.
    """
    chain_check(chain, source)

    def compute():
        positions_entry, meta = store.get(
            ("positions", chain, wallet.lower()),
            lambda: vaults.fetch_vaults(wallet, chain_id=chain),
            fresh=fresh,
        )
        pools_entry, pools_meta = store.get(
            ("pools", chain, source), lambda: api.fetch_pools(chain, source=source), fresh=fresh
        )
        if pools_meta.cache == "miss":
            meta = Meta(meta.cache, meta.age, meta.upstream_ms + pools_meta.upstream_ms)
        rows = web_rotation.rotation_rows(
            positions_entry.value, pools_entry.value, PROFILES[profile], quote=quote or None
        )
        return finite(rows), meta, min(positions_entry.at, pools_entry.at)

    rows, meta, fetched_at = await run_in_threadpool(compute)
    meta.apply(response, 60)
    await web_verdicts.log_rows(user, rows)
    await web_verdicts.attach_history(user, rows)
    return {"rows": rows, "fetchedAt": fetched_at}


@app.get("/leaderboard", dependencies=[Depends(market_user)])
def board(
    chain: int = 4663,
    sort: Literal["roi", "pnl", "apr", "30d"] = "roi",
    fresh: Fresh = False,
    response: Response = None,
):
    chain_check(chain)
    entry, meta = store.get(
        ("leaderboard", chain),
        lambda: vaults.fetch_public_vaults(chain),
        ttl=300,
        stale=1800,
        fresh=fresh,
    )
    meta.apply(response, 300)
    ranked = leaderboard.rank(entry.value, sort=sort)
    return {
        "rows": finite(
            [asdict(r) | {"url": r.vault.url, "candidate": r.candidate} for r in ranked.vaults]
        ),
        "owners": finite(
            [
                {
                    "address": o.address,
                    "name": o.label,
                    "tvl": o.tvl,
                    "pnl": o.pnl,
                    "roi": o.roi_pct,
                    "vaults": len(o.vaults),
                }
                for o in ranked.owners
            ]
        ),
        "fetchedAt": entry.at,
    }


@app.get("/review", dependencies=[Depends(market_user)])
def review(
    address: Annotated[str, Query(pattern=r"^0x[a-fA-F0-9]{40}$")],
    chain: int = 4663,
    fresh: Fresh = False,
    response: Response = None,
):
    from .vault_eval import evaluate
    from .vault_review import fetch_review

    chain_check(chain)

    def load():
        rv = fetch_review(chain, address)
        return finite(asdict(evaluate(rv)))

    entry, meta = store.get(
        ("review", chain, address.lower()), load, ttl=300, stale=1800, fresh=fresh
    )
    meta.apply(response, 300)
    return {"evaluation": entry.value, "fetchedAt": entry.at}
