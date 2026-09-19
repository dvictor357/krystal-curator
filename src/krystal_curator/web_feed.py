"""Browser-fed data: Krystal's Cloudflare challenges datacenter egress, so the browser
fetches Krystal and posts the raw payloads here; the server parses, scores and caches.

A *recipe* names the requests one dataset needs (`steps`: name → url + params). The
browser runs them and posts `payloads` (name → JSON, or `{"__error": text}`) with the
recipe's `round`; `ingest` returns either `{"done": true}` or `{"next": recipe}` for a
further round (vault details after the vault list, remaining leaderboard pages).

`CURATOR_SERVER_FETCH=true` keeps the old server-side fetch path (for egress Krystal
accepts); the recipe machinery is then never handed to the browser.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

from . import api, vaults
from .models import Pool
from .vault_review import build_review, review_sources
from .web_cache import Cache

MAX_PAYLOAD = 8 * 1024 * 1024
PARTIAL_TTL = 120  # seconds a multi-round ingest may take between rounds


def server_fetch_enabled() -> bool:
    return os.environ.get("CURATOR_SERVER_FETCH", "false").lower() == "true"


# ---- recipes ----------------------------------------------------------------------------


def _step(name: str, url: str, params: dict | None = None) -> dict:
    return {"name": name, "url": url, "params": {k: str(v) for k, v in (params or {}).items()}}


def recipe_pools(chain: int) -> dict:
    return {
        "kind": "pools",
        "chain": chain,
        "round": 1,
        "steps": [
            _step(
                "pools",
                api.PUBLIC_TOP_POOLS,
                {"skipCheckAutomation": "true", "chainId": chain, "limit": 5000},
            )
        ],
    }


POSITION_QUERIES = {
    "owned_auto": ({"isAutoFarmVault": "true", "perPage": 100}, "ownerAddress", True),
    "owned_std": ({"isAutoFarmVault": "false", "perPage": 100}, "ownerAddress", True),
    "joined": ({"perPage": 100}, "userAddress", False),
    "joined_auto": ({"isAutoFarmVault": "true", "perPage": 100}, "userAddress", False),
}


def recipe_positions(chain: int, wallet: str) -> dict:
    return {
        "kind": "positions",
        "chain": chain,
        "wallet": wallet,
        "round": 1,
        "steps": [
            _step(name, f"{vaults.VAULTS}/profile", {**params, who: wallet})
            for name, (params, who, _owned) in POSITION_QUERIES.items()
        ],
    }


def recipe_leaderboard(chain: int, pages: list[int] | None = None) -> dict:
    pages = pages or [1]
    return {
        "kind": "leaderboard",
        "chain": chain,
        "round": 1 if pages == [1] else 2,
        "steps": [
            _step(
                f"page_{n}",
                vaults.VAULTS,
                {"chainIds": chain, "isAutoFarmVault": "true", "perPage": 100, "page": n},
            )
            for n in pages
        ],
    }


def recipe_review(chain: int, address: str) -> dict:
    return {
        "kind": "review",
        "chain": chain,
        "address": address.lower(),
        "round": 1,
        "steps": [
            _step(name, url, params)
            for name, (url, params) in review_sources(chain, address).items()
        ],
    }


# ---- ingest -----------------------------------------------------------------------------


class FeedError(ValueError):
    """Payload shape the browser sent cannot be parsed; the message is safe to show."""


def _payload(payloads: dict[str, Any], name: str) -> Any:
    raw = payloads.get(name)
    if raw is None:
        raise FeedError(f"missing payload {name!r}")
    if isinstance(raw, dict) and "__error" in raw:
        raise FeedError(f"{name}: {raw['__error']}")
    return raw


def ingest_pools(cache: Cache, chain: int, payloads: dict[str, Any], upstream_ms: float) -> dict:
    data = _payload(payloads, "pools")
    rows = data.get("result") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise FeedError("pools: unexpected payload")
    pools = [Pool.from_public(x) for x in rows if isinstance(x, dict)]
    cache.put(("pools", chain, "krystal"), pools, upstream_ms)
    return {"done": True, "count": len(pools)}


def ingest_positions(
    cache: Cache, chain: int, wallet: str, round_: int, payloads: dict[str, Any], upstream_ms: float
) -> dict:
    partial_key = ("positions-partial", chain, wallet.lower())
    if round_ == 1:
        seen: dict[str, vaults.Vault] = {}
        for name, (_params, _who, owned) in POSITION_QUERIES.items():
            try:
                data = _payload(payloads, name)
            except FeedError:
                continue  # one profile query failing must not blank the wallet
            for d in (data.get("data") if isinstance(data, dict) else None) or []:
                v = vaults._parse_vault(d, owned=owned)
                if v.chain_id != chain:
                    continue
                if v.address in seen:
                    seen[v.address].owned |= owned
                    continue
                seen[v.address] = v
        if not seen:
            cache.put(("positions", chain, wallet.lower()), [], upstream_ms)
            return {"done": True, "count": 0}
        cache.put(partial_key, seen, upstream_ms)
        return {
            "next": {
                "kind": "positions",
                "chain": chain,
                "wallet": wallet,
                "round": 2,
                "steps": [
                    _step(f"detail_{addr}", f"{vaults.VAULTS}/{chain}/{addr}") for addr in seen
                ],
            }
        }
    partial = cache.peek(partial_key)
    if partial is None:
        raise FeedError("positions: round 1 expired, start again")
    seen = dict(partial.value)
    for addr, v in seen.items():
        try:
            detail = _payload(payloads, f"detail_{addr}")
        except FeedError:
            continue
        if isinstance(detail, dict):
            vaults._attach_strategies(v, detail)
    out = sorted(seen.values(), key=lambda v: v.tvl, reverse=True)
    cache.put(("positions", chain, wallet.lower()), out, upstream_ms + partial.upstream_ms)
    return {"done": True, "count": len(out)}


def ingest_leaderboard(
    cache: Cache, chain: int, round_: int, payloads: dict[str, Any], upstream_ms: float
) -> dict:
    partial_key = ("leaderboard-partial", chain)
    if round_ == 1:
        data = _payload(payloads, "page_1")
        if not isinstance(data, dict):
            raise FeedError("vaults: unexpected list payload")
        out = [
            v
            for v in (vaults._parse_vault(d, owned=False) for d in data.get("data") or [])
            if v.chain_id == chain
        ]
        pages = int((data.get("pagination") or {}).get("totalPage") or 1)
        if pages <= 1:
            cache.put(("leaderboard", chain), out, upstream_ms)
            return {"done": True, "count": len(out)}
        cache.put(partial_key, out, upstream_ms)
        return {"next": recipe_leaderboard(chain, list(range(2, pages + 1)))}
    partial = cache.peek(partial_key)
    if partial is None:
        raise FeedError("leaderboard: round 1 expired, start again")
    out = list(partial.value)
    for name, raw in payloads.items():
        if not name.startswith("page_") or not isinstance(raw, dict) or "__error" in raw:
            continue
        out.extend(
            v
            for v in (vaults._parse_vault(d, owned=False) for d in raw.get("data") or [])
            if v.chain_id == chain
        )
    cache.put(("leaderboard", chain), out, upstream_ms + partial.upstream_ms)
    return {"done": True, "count": len(out)}


def ingest_review(
    cache: Cache, chain: int, address: str, payloads: dict[str, Any], upstream_ms: float
) -> dict:
    from .vault_eval import evaluate
    from .web_api import finite

    try:
        rv = build_review(chain, address, payloads)
    except api.KrystalError as e:
        raise FeedError(str(e)) from None
    cache.put(("review", chain, address.lower()), finite(asdict(evaluate(rv))), upstream_ms)
    return {"done": True}
