"""Private HTTP bridge for Curator web; run behind the Next.js server, never publicly."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from tortoise.contrib.fastapi import RegisterTortoise

from . import (
    api,
    leaderboard,
    vaults,
    web_alerts,
    web_feed,
    web_rotation,
    web_usage,
    web_verdicts,
)
from .models import CHAIN_SLUG, Pool, default_quote
from .position import simulate
from .profiles import PROFILES
from .scoring import curate
from .web_auth import authorize, market_user, router
from .web_cache import Cache, Meta
from .web_db import TORTOISE_ORM, User

log = logging.getLogger(__name__)
store = Cache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(app, config=TORTOISE_ORM):
        tasks = [asyncio.create_task(web_alerts.loop(store)), asyncio.create_task(web_usage.loop())]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            try:
                await web_usage.flush()
            except Exception:
                log.warning("usage: final flush failed", exc_info=True)


app = FastAPI(title="Curator analytics", dependencies=[Depends(authorize)], lifespan=lifespan)
app.include_router(router)
app.middleware("http")(web_usage.middleware)


Fresh = Annotated[bool, Query(description="Bypass the cache once (manual refresh)")]


def quote_for(chain: int, quote: str) -> str | None:
    """'' → the chain's usual quote token; 'any' → no quote filter."""
    if quote.lower() == "any":
        return None
    return quote or default_quote(chain)


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


class NeedFeed(Exception):
    """Browser-fed mode: nothing usable cached — here is what to fetch and post back.

    Answered as 200 `{"needFeed": [...]}` (a handshake, not an error: browsers log every
    4xx to the console, and this happens on every first load).
    """

    def __init__(self, recipes: list[dict]):
        super().__init__("need feed")
        self.recipes = recipes


@app.exception_handler(NeedFeed)
async def _need_feed(request: Request, exc: NeedFeed):
    return JSONResponse({"needFeed": exc.recipes}, headers={"Cache-Control": "no-store"})


def scoped(key: tuple, user: User) -> tuple:
    """Browser-fed entries live per user: one user cannot poison another's screener."""
    return key if web_feed.server_fetch_enabled() else (*key, str(user.id))


def serve(key: tuple, recipe: dict, fetch, user: User, *, ttl: int, stale: int, fresh: bool):
    """(entry, meta, refresh_recipe). Server-fetch mode behaves as before; browser-fed mode
    serves the user's own cached copy, asks for a refresh past `ttl`, refuses past `stale`."""
    if web_feed.server_fetch_enabled():
        entry, meta = store.get(key, fetch, ttl=ttl, stale=stale, fresh=fresh)
        return entry, meta, None
    entry = store.peek(scoped(key, user))
    age = time.time() - entry.at if entry else None
    if entry is None or fresh or age >= stale:
        raise NeedFeed([recipe])
    if age >= ttl:
        return entry, Meta("stale", age, 0.0), recipe
    return entry, Meta("hit", age, 0.0), None


def with_refresh(body: dict, *recipes: dict | None) -> dict:
    wanted = [r for r in recipes if r]
    if wanted:
        body["refreshFeed"] = wanted
    return body


class FeedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chain: int
    round: int = Field(ge=1, le=2)
    wallet: str = Field(default="", pattern=r"^(0x[a-fA-F0-9]{40})?$")
    address: str = Field(default="", pattern=r"^(0x[a-fA-F0-9]{40})?$")
    upstreamMs: float = Field(default=0, ge=0, le=600_000)
    payloads: dict[str, Any]


@app.post("/feed/{kind}")
async def feed(
    kind: Literal["pools", "positions", "leaderboard", "review"],
    body: FeedBody,
    user: Annotated[User, Depends(market_user)],
    request: Request,
):
    """The browser posts what it fetched from Krystal; we parse, score and cache it."""
    if web_feed.server_fetch_enabled():
        raise HTTPException(409, "This deployment fetches server-side; nothing to post.")
    if int(request.headers.get("content-length") or 0) > web_feed.MAX_PAYLOAD:
        raise HTTPException(413, "Payload too large.")
    chain_check(body.chain)
    scope = str(user.id)
    cache = _UserScopedCache(store, scope)

    def run():
        try:
            if kind == "pools":
                return web_feed.ingest_pools(cache, body.chain, body.payloads, body.upstreamMs)
            if kind == "positions":
                if not body.wallet:
                    raise web_feed.FeedError("positions: wallet required")
                return web_feed.ingest_positions(
                    cache, body.chain, body.wallet, body.round, body.payloads, body.upstreamMs
                )
            if kind == "leaderboard":
                return web_feed.ingest_leaderboard(
                    cache, body.chain, body.round, body.payloads, body.upstreamMs
                )
            if not body.address:
                raise web_feed.FeedError("review: address required")
            return web_feed.ingest_review(
                cache, body.chain, body.address, body.payloads, body.upstreamMs
            )
        except web_feed.FeedError as e:
            raise HTTPException(422, str(e)) from None

    return await run_in_threadpool(run)


class _UserScopedCache:
    """The shared cache with every key suffixed by the user id (browser-fed entries)."""

    def __init__(self, inner: Cache, scope: str):
        self.inner, self.scope = inner, scope

    def put(self, key: tuple, value, upstream_ms: float = 0.0):
        return self.inner.put((*key, self.scope), value, upstream_ms)

    def peek(self, key: tuple):
        return self.inner.peek((*key, self.scope))


@app.get("/pools")
def pools(
    user: Annotated[User, Depends(market_user)],
    chain: int = 4663,
    source: Literal["krystal"] = "krystal",
    profile: Literal["conservative", "balanced", "aggressive", "degen"] = "balanced",
    quote: Annotated[str, Query(max_length=20, pattern=r"^[^\s&=?/#]*$")] = "",
    size: Annotated[float, Query(ge=1, le=100_000_000, allow_inf_nan=False)] = 10000,
    fresh: Fresh = False,
    response: Response = None,
):
    chain_check(chain, source)
    entry, meta, refresh = serve(
        ("pools", chain, source),
        web_feed.recipe_pools(chain),
        lambda: api.fetch_pools(chain, source=source),
        user,
        ttl=60,
        stale=600,
        fresh=fresh,
    )
    meta.apply(response, 60)
    return with_refresh(
        {
            "rows": pool_rows(entry.value, profile, quote_for(chain, quote) or "", size),
            "fetchedAt": entry.at,
            "source": source,
            "demo": False,
        },
        refresh,
    )


@app.get("/positions")
def positions(
    wallet: Annotated[str, Query(pattern=r"^0x[a-fA-F0-9]{40}$")],
    user: Annotated[User, Depends(market_user)],
    chain: int = 4663,
    fresh: Fresh = False,
    response: Response = None,
):
    chain_check(chain)
    entry, meta, refresh = serve(
        ("positions", chain, wallet.lower()),
        web_feed.recipe_positions(chain, wallet),
        lambda: vaults.fetch_vaults(wallet, chain_id=chain),
        user,
        ttl=60,
        stale=600,
        fresh=fresh,
    )
    meta.apply(response, 60)
    return with_refresh(
        {
            "rows": finite([asdict(v) | {"url": v.url} for v in entry.value]),
            "fetchedAt": entry.at,
        },
        refresh,
    )


@app.get("/rotations")
async def rotations(
    wallet: Annotated[str, Query(pattern=r"^0x[a-fA-F0-9]{40}$")],
    user: Annotated[User, Depends(market_user)],
    chain: int = 4663,
    source: Literal["krystal"] = "krystal",
    profile: Literal["conservative", "balanced", "aggressive", "degen"] = "balanced",
    quote: Annotated[str, Query(max_length=20, pattern=r"^[^\s&=?/#]*$")] = "",
    fresh: Fresh = False,
    response: Response = None,
):
    """Opportunity cost per open position: same dollars in the profile's best pools.

    Every verdict shown is logged so the position can later carry its own track record.
    """
    chain_check(chain, source)

    def compute():
        needed: list[dict] = []
        try:
            positions_entry, meta, refresh_p = serve(
                ("positions", chain, wallet.lower()),
                web_feed.recipe_positions(chain, wallet),
                lambda: vaults.fetch_vaults(wallet, chain_id=chain),
                user,
                ttl=60,
                stale=600,
                fresh=fresh,
            )
        except NeedFeed as e:
            needed += e.recipes
        try:
            pools_entry, pools_meta, refresh_q = serve(
                ("pools", chain, source),
                web_feed.recipe_pools(chain),
                lambda: api.fetch_pools(chain, source=source),
                user,
                ttl=60,
                stale=600,
                fresh=fresh,
            )
        except NeedFeed as e:
            needed += e.recipes
        if needed:
            raise NeedFeed(needed)
        if pools_meta.cache == "miss":
            meta = Meta(meta.cache, meta.age, meta.upstream_ms + pools_meta.upstream_ms)
        rows = web_rotation.rotation_rows(
            positions_entry.value,
            pools_entry.value,
            PROFILES[profile],
            quote=quote_for(chain, quote),
        )
        return (
            finite(rows),
            meta,
            min(positions_entry.at, pools_entry.at),
            [r for r in (refresh_p, refresh_q) if r],
        )

    rows, meta, fetched_at, refresh = await run_in_threadpool(compute)
    meta.apply(response, 60)
    await web_verdicts.log_rows(user, rows)
    await web_verdicts.record_samples(rows)
    await web_verdicts.attach_history(user, rows)
    return with_refresh({"rows": rows, "fetchedAt": fetched_at}, *refresh)


@app.get("/usage")
async def usage(
    user: Annotated[User, Depends(market_user)],
    days: Annotated[int, Query(ge=1, le=90)] = 30,
):
    """Admin only: who uses what, per day and per route, plus the top accounts."""
    web_usage.require_admin(user)
    return await web_usage.report(days)


@app.get("/track-record")
async def track_record(days: Annotated[int, Query(ge=7, le=90)] = 30, response: Response = None):
    """Aggregate, anonymous: every verdict in the window against what followed."""
    response.headers["Cache-Control"] = "private, max-age=300"
    return finite(await web_verdicts.track_record(days))


@app.get("/leaderboard")
def board(
    user: Annotated[User, Depends(market_user)],
    chain: int = 4663,
    sort: Literal["roi", "pnl", "apr", "30d"] = "roi",
    fresh: Fresh = False,
    response: Response = None,
):
    chain_check(chain)
    entry, meta, refresh = serve(
        ("leaderboard", chain),
        web_feed.recipe_leaderboard(chain),
        lambda: vaults.fetch_public_vaults(chain),
        user,
        ttl=300,
        stale=1800,
        fresh=fresh,
    )
    meta.apply(response, 300)
    ranked = leaderboard.rank(entry.value, sort=sort)
    return with_refresh(
        {
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
        },
        refresh,
    )


@app.get("/review")
def review(
    address: Annotated[str, Query(pattern=r"^0x[a-fA-F0-9]{40}$")],
    user: Annotated[User, Depends(market_user)],
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

    entry, meta, refresh = serve(
        ("review", chain, address.lower()),
        web_feed.recipe_review(chain, address),
        load,
        user,
        ttl=300,
        stale=1800,
        fresh=fresh,
    )
    meta.apply(response, 300)
    return with_refresh({"evaluation": entry.value, "fetchedAt": entry.at}, refresh)
