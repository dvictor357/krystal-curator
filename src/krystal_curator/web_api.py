"""Private HTTP bridge for Curator web; run behind the Next.js server, never publicly."""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import asdict
from threading import Lock
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from tortoise.contrib.fastapi import RegisterTortoise

from . import api, leaderboard, vaults
from .models import CHAIN_SLUG, Pool
from .position import simulate
from .profiles import PROFILES
from .scoring import curate
from .web_auth import authorize, market_user, router
from .web_db import TORTOISE_ORM


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(app, config=TORTOISE_ORM):
        yield


app = FastAPI(title="Curator analytics", dependencies=[Depends(authorize)], lifespan=lifespan)
app.include_router(router)
_cache: OrderedDict = OrderedDict()
_lock = Lock()


def cached(key: tuple, fetch, ttl: int = 90):
    # ponytail: one process / global fetch lock; shared cache + per-key locks if traffic grows.
    with _lock:
        previous = _cache.get(key)
        if previous and time.time() - previous[0] < ttl:
            return previous[1], previous[0]
        try:
            result = fetch()
        except api.KrystalError:
            raise HTTPException(502, "Data provider unavailable. Try again shortly.") from None
        timestamp = time.time()
        _cache[key] = (timestamp, result)
        _cache.move_to_end(key)
        while len(_cache) > 64:
            _cache.popitem(last=False)
        return result, timestamp


def chain_check(chain: int, source: str = "krystal"):
    if chain not in CHAIN_SLUG or (source == "rhpools" and chain != 4663):
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
    source: Literal["krystal", "rhpools"] = "krystal",
    profile: Literal["conservative", "balanced", "aggressive", "degen"] = "balanced",
    quote: Annotated[str, Query(max_length=20, pattern=r"^[A-Za-z0-9]*$")] = "USDG",
    size: Annotated[float, Query(ge=1, le=100_000_000, allow_inf_nan=False)] = 10000,
):
    chain_check(chain, source)
    data, timestamp = cached(
        ("pools", chain, source), lambda: api.fetch_pools(chain, source=source)
    )
    return {
        "rows": pool_rows(data, profile, quote, size),
        "fetchedAt": timestamp,
        "source": source,
        "demo": False,
    }


@app.get("/positions", dependencies=[Depends(market_user)])
def positions(wallet: Annotated[str, Query(pattern=r"^0x[a-fA-F0-9]{40}$")], chain: int = 4663):
    chain_check(chain)
    data, timestamp = cached(
        ("positions", chain, wallet.lower()), lambda: vaults.fetch_vaults(wallet, chain_id=chain)
    )
    return {"rows": finite([asdict(v) | {"url": v.url} for v in data]), "fetchedAt": timestamp}


@app.get("/leaderboard", dependencies=[Depends(market_user)])
def board(chain: int = 4663, sort: Literal["roi", "pnl", "apr", "30d"] = "roi"):
    chain_check(chain)
    data, timestamp = cached(("leaderboard", chain), lambda: vaults.fetch_public_vaults(chain), 300)
    ranked = leaderboard.rank(data, sort=sort)
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
        "fetchedAt": timestamp,
    }


@app.get("/review", dependencies=[Depends(market_user)])
def review(address: Annotated[str, Query(pattern=r"^0x[a-fA-F0-9]{40}$")], chain: int = 4663):
    from .vault_eval import evaluate
    from .vault_review import fetch_review

    chain_check(chain)

    def load():
        rv = fetch_review(chain, address)
        return finite(asdict(evaluate(rv)))

    data, timestamp = cached(("review", chain, address.lower()), load, 300)
    return {"evaluation": data, "fetchedAt": timestamp}
