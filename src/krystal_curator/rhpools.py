"""robinhoodpools (rhpools) as a pool feed: chain-indexed, USDG-quoted, no key.

Public instance: https://rhpools.lol  ·  local: `rhpools --port 8196` from
https://github.com/wock9000/robinhoodpools (AGPL; consumed over HTTP only).

`/api/lp/pools` serves one window per request (1h / 24h / 7d / 30d), paged by
`limit`/`offset` (max 150 per page), sorted by fees. There is no id filter, so we
take the top N of every window and join on pool id. A window the service cannot
serve (the public instance answers 503 for 7d / 30d when its aggregation times
out) is dropped, not zero-filled: the Pool records it in `unknown`.

Only chain 4663 (Robinhood) exists there.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from . import net
from .models import ROBINHOOD, Pool

log = logging.getLogger("krystal.rhpools")

DEFAULT_URL = "https://rhpools.lol"
WINDOWS = ("1h", "24h", "7d", "30d")
PAGE = 150  # server cap
_HEADERS = {"Accept": "application/json", "User-Agent": "krystal-curator/0.1"}


class RhpoolsError(RuntimeError):
    pass


class WindowUnavailable(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


# A window that answered 502/503/504 is skipped for this long before being retried:
# the public instance takes ~15 s to time out on 7d / 30d and a TUI refresh should
# not pay that on every tick.
UNAVAILABLE_COOLDOWN_S = 600.0
_unavailable_until: dict[tuple[str, str], float] = {}


def _get_page(
    client: httpx.Client, base: str, window: str, offset: int, limit: int
) -> dict[str, Any]:
    params = {"window": window, "limit": limit, "offset": offset, "sort": "fees", "order": "desc"}
    # 502/503/504 here mean "this window's aggregation timed out" and take ~15 s each:
    # handled by the caller with a cooldown, never retried blindly. Transport errors are.
    r = net.get(
        f"{base}/api/lp/pools",
        params=params,
        headers=_HEADERS,
        client=client,
        retry_statuses=(429,),
    )
    if r.status_code != 200:
        raise (
            WindowUnavailable(r.status_code)
            if r.status_code in (502, 503, 504)
            else net.status_error(r, f"{window} offset={offset}")
        )
    data = r.json()
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise RhpoolsError(f"{window} offset={offset}: unexpected payload")
    return data


def fetch_window(
    client: httpx.Client, base: str, window: str, top: int
) -> dict[str, dict[str, Any]] | None:
    """Rows of one window keyed by pool id; None if the service cannot serve it."""
    key = (base, window)
    if _unavailable_until.get(key, 0.0) > time.monotonic():
        log.info("rhpools %s window skipped (cooldown after last failure)", window)
        return None
    rows: dict[str, dict[str, Any]] = {}
    offset = 0
    while offset < top:
        limit = min(PAGE, top - offset)
        try:
            page = _get_page(client, base, window, offset, limit)
        except WindowUnavailable as e:
            if rows:
                raise RhpoolsError(f"{window} offset={offset}: HTTP {e.status}") from None
            log.warning("rhpools %s window unavailable (%s)", window, e.status)
            _unavailable_until[key] = time.monotonic() + UNAVAILABLE_COOLDOWN_S
            return None
        except (net.HttpError, ValueError) as e:
            raise RhpoolsError(f"{window} offset={offset}: {e}") from None
        got = page["rows"]
        for row in got:
            pid = str(row.get("id") or "").lower()
            if pid:
                rows[pid] = row
        if len(got) < limit:
            break
        offset += limit
    return rows


def fetch_pools(
    chain_id: int = ROBINHOOD,
    *,
    base: str = DEFAULT_URL,
    top: int = 300,
    timeout: float = 30.0,
) -> list[Pool]:
    """Top `top` pools by 24h fees, with every window the service could serve.

    Pools missing from the 24h page but present in others are skipped: 24h is the
    identity + ranking window. Missing 1h/7d/30d rows for a pool become unknown
    stats on that pool only.
    """
    if chain_id != ROBINHOOD:
        raise RhpoolsError(f"rhpools indexes chain {ROBINHOOD} only, not {chain_id}")
    base = base.rstrip("/")
    windows: dict[str, dict[str, dict[str, Any]]] = {}
    # one request per window and the public instance spends ~15 s timing out on the
    # long ones: run them side by side so the wall clock is the slowest, not the sum.
    with (
        httpx.Client(timeout=timeout) as client,
        ThreadPoolExecutor(max_workers=len(WINDOWS)) as pool,
    ):
        futures = {w: pool.submit(fetch_window, client, base, w, top) for w in WINDOWS}
        for w, fut in futures.items():
            got = fut.result()
            if got is not None:
                windows[w] = got
    if "24h" not in windows:
        raise RhpoolsError(f"{base}: 24h window unavailable; nothing to rank")
    served = [w for w in WINDOWS if w in windows]
    pools: list[Pool] = []
    for pid, row24 in windows["24h"].items():
        rows = {"24h": row24}
        for w in served:
            r = windows[w].get(pid)
            if r is not None:
                rows[w] = r
        pools.append(Pool.from_rhpools(rows, chain_id=chain_id))
    log.info("rhpools: %d pools, windows %s", len(pools), "/".join(served))
    return pools
