"""HTTP access to Krystal.

Public (no key):  https://api.krystal.app/all/v2/lp_explorer/top_pools
Cloud (KC-APIKey): https://cloud-api.krystal.app/v1  — only used for tx counts.
"""

from __future__ import annotations

import os
import time
from typing import Any

from . import net
from .models import Pool

PUBLIC_TOP_POOLS = "https://api.krystal.app/all/v2/lp_explorer/top_pools"
CLOUD_BASE = "https://cloud-api.krystal.app/v1"
CLOUD_KEY_ENV = "KRYSTAL_CLOUD_KEY"
WALLET_ENV = "KRYSTAL_WALLET"

_HEADERS = {"Accept": "application/json", "User-Agent": "krystal-curator/0.1"}


class KrystalError(RuntimeError):
    pass


SOURCES = ("krystal",)


def fetch_pools(
    chain_id: int,
    *,
    source: str = "krystal",
    limit: int = 5000,
    timeout: float = 30.0,
    **_ignored: Any,
) -> list[Pool]:
    """Pools on `chain_id` from the configured feed.

    `krystal`: the public LP-explorer feed (every chain Krystal lists). A second,
    chain-indexed feed was removed; `reconcile.py` stays for the day one returns.
    """
    if source != "krystal":
        raise KrystalError(f"unknown pool source {source!r}; use one of {', '.join(SOURCES)}")
    return fetch_krystal_pools(chain_id, limit=limit, timeout=timeout)


def reference_source(chain_id: int, source: str) -> str | None:
    """The other feed to reconcile against; None until a second feed exists again."""
    return None


def fetch_reference_pools(
    chain_id: int, *, source: str = "krystal", **kw: Any
) -> list[Pool] | None:
    """Pools from the *other* feed for cross-checking; None if no other feed covers the chain."""
    other = reference_source(chain_id, source)
    if other is None:
        return None
    return fetch_pools(chain_id, source=other, **kw)


def fetch_krystal_pools(chain_id: int, *, limit: int = 5000, timeout: float = 30.0) -> list[Pool]:
    """All pools Krystal tracks on `chain_id` (server-side filtered)."""
    params: dict[str, Any] = {
        "skipCheckAutomation": "true",
        "chainId": chain_id,
        "limit": limit,
    }
    try:
        r = net.get(PUBLIC_TOP_POOLS, params=params, headers=_HEADERS, timeout=timeout)
        if r.status_code != 200:
            raise net.status_error(r, f"top_pools chainId={chain_id}")
        data = r.json()
    except (net.HttpError, ValueError) as e:
        raise KrystalError(f"top_pools chainId={chain_id}: {e}") from None
    rows = data.get("result") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise KrystalError(
            f"top_pools chainId={chain_id}: unexpected payload {type(data).__name__}"
        )
    return [Pool.from_public(x) for x in rows]


def cloud_key() -> str | None:
    key = os.environ.get(CLOUD_KEY_ENV) or None
    net.register_secret(key)  # never let it into an error string, log line or toast
    return key


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
    net.register_secret(key)
    try:
        r = net.get(url, params=params, headers={**_HEADERS, "KC-APIKey": key}, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
    except (net.HttpError, ValueError):
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return len(v)
    return None
