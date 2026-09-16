"""HTTP access to Krystal.

Public (no key):  https://api.krystal.app/all/v2/lp_explorer/top_pools
Cloud (KC-APIKey): https://cloud-api.krystal.app/v1  — only used for tx counts.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from .models import Pool

PUBLIC_TOP_POOLS = "https://api.krystal.app/all/v2/lp_explorer/top_pools"
CLOUD_BASE = "https://cloud-api.krystal.app/v1"
CLOUD_KEY_ENV = "KRYSTAL_CLOUD_KEY"
WALLET_ENV = "KRYSTAL_WALLET"

_HEADERS = {"Accept": "application/json", "User-Agent": "krystal-curator/0.1"}


class KrystalError(RuntimeError):
    pass


SOURCES = ("krystal", "rhpools")


def fetch_pools(
    chain_id: int,
    *,
    source: str = "krystal",
    rhpools_url: str | None = None,
    rhpools_top: int = 300,
    limit: int = 5000,
    timeout: float = 30.0,
) -> list[Pool]:
    """Pools on `chain_id` from the configured feed.

    `krystal`: the public LP-explorer feed (every chain Krystal lists).
    `rhpools`: robinhoodpools' chain-indexed feed (Robinhood only, no σ / drawdown).
    Both raise KrystalError so callers keep one except clause.
    """
    if source == "rhpools":
        from . import rhpools

        try:
            return rhpools.fetch_pools(
                chain_id, base=rhpools_url or rhpools.DEFAULT_URL, top=rhpools_top, timeout=timeout
            )
        except rhpools.RhpoolsError as e:
            raise KrystalError(str(e)) from e
    if source != "krystal":
        raise KrystalError(f"unknown pool source {source!r}; use one of {', '.join(SOURCES)}")
    return fetch_krystal_pools(chain_id, limit=limit, timeout=timeout)


def fetch_krystal_pools(chain_id: int, *, limit: int = 5000, timeout: float = 30.0) -> list[Pool]:
    """All pools Krystal tracks on `chain_id` (server-side filtered)."""
    params: dict[str, Any] = {
        "skipCheckAutomation": "true",
        "chainId": chain_id,
        "limit": limit,
    }
    try:
        r = httpx.get(PUBLIC_TOP_POOLS, params=params, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise KrystalError(f"top_pools chainId={chain_id}: {e}") from e
    rows = data.get("result") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise KrystalError(
            f"top_pools chainId={chain_id}: unexpected payload {type(data).__name__}"
        )
    return [Pool.from_public(x) for x in rows]


def cloud_key() -> str | None:
    return os.environ.get(CLOUD_KEY_ENV) or None


def wallet() -> str | None:
    return os.environ.get(WALLET_ENV) or None


def fetch_tx_count_24h(pool: Pool, key: str, *, timeout: float = 30.0) -> int | None:
    """Number of swaps/mints/burns in the last 24h via Cloud API.

    Costs Cloud credits per call. Response schema is undocumented in the
    swagger (additionalProperties: true) so parsing is defensive: a bare list,
    or an object holding the first list-valued field.
    """
    now = int(time.time())
    url = f"{CLOUD_BASE}/pools/{pool.chain_id}/{pool.address}/transactions"
    params = {"startTime": now - 86400, "endTime": now, "limit": 5000}
    try:
        r = httpx.get(url, params=params, headers={**_HEADERS, "KC-APIKey": key}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError:
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return len(v)
    return None
