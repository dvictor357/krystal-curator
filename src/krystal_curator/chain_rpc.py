"""Live pool prices straight from chain RPC: the one input range/edge alerts cannot wait for.

Reads `slot0()` on V3-style pools and `StateView.getSlot0(poolId)` on V4, converts
sqrtPriceX96 to a human price with token decimals, and calibrates orientation against the
last price the feed reported so alerts compare like with like. No indexer, one call per
pool, public endpoints; anything that fails leaves the feed's value untouched.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass

from eth_utils import function_signature_to_4byte_selector

from . import net
from .models import Pool
from .positions import Position

log = logging.getLogger(__name__)

RPC_URLS: dict[int, str] = {
    1: "https://ethereum-rpc.publicnode.com",
    10: "https://mainnet.optimism.io",
    56: "https://bsc-rpc.publicnode.com",
    137: "https://polygon-bor-rpc.publicnode.com",
    999: "https://rpc.hyperliquid.xyz/evm",
    4663: "https://rpc.mainnet.chain.robinhood.com",
    8453: "https://mainnet.base.org",
    42161: "https://arb1.arbitrum.io/rpc",
    43114: "https://avalanche-c-chain-rpc.publicnode.com",
}
# Uniswap V4 StateView per chain (reads pool state from the PoolManager singleton).
STATE_VIEW: dict[int, str] = {
    4663: "0xf3334192d15450cdd385c8b70e03f9a6bd9e673b",
}
SLOT0 = "0x" + function_signature_to_4byte_selector("slot0()").hex()
GET_SLOT0 = "0x" + function_signature_to_4byte_selector("getSlot0(bytes32)").hex()
DECIMALS = "0x" + function_signature_to_4byte_selector("decimals()").hex()
NATIVE = {
    "0x0000000000000000000000000000000000000000",
    "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",  # Krystal's placeholder for the native coin
}
Q96 = 2**96
_decimals_cache: dict[tuple[int, str], int] = {}


def rpc_url(chain: int) -> str | None:
    """CURATOR_RPC_<chain> overrides the public default; set it empty to disable."""
    override = os.environ.get(f"CURATOR_RPC_{chain}")
    if override is not None:
        return override or None
    return RPC_URLS.get(chain)


def _calls(chain: int, calls: list[tuple[str, str]], timeout: float = 20.0) -> list[str | None]:
    """Batched eth_call; a failed item is None."""
    url = rpc_url(chain)
    if not url or not calls:
        return [None] * len(calls)
    body = [
        {
            "jsonrpc": "2.0",
            "id": i,
            "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"],
        }
        for i, (to, data) in enumerate(calls)
    ]
    try:
        r = net.post(url, json=body, timeout=timeout)
        rows = r.json() if r.status_code == 200 else []
    except (net.HttpError, ValueError) as e:
        log.warning("rpc %s: %s", chain, e)
        return [None] * len(calls)
    out: list[str | None] = [None] * len(calls)
    for row in rows if isinstance(rows, list) else []:
        i = row.get("id")
        res = row.get("result")
        if isinstance(i, int) and 0 <= i < len(calls) and isinstance(res, str) and len(res) > 2:
            out[i] = res
    return out


def _word(hex_data: str, index: int = 0) -> int | None:
    data = hex_data.removeprefix("0x")
    chunk = data[index * 64 : (index + 1) * 64]
    return int(chunk, 16) if len(chunk) == 64 else None


def decimals(chain: int, tokens: list[str]) -> dict[str, int]:
    """ERC-20 decimals, cached for the process; the native token is 18."""
    out: dict[str, int] = {}
    missing = []
    for t in tokens:
        t = t.lower()
        if t in NATIVE or not t:
            out[t] = 18
        elif (chain, t) in _decimals_cache:
            out[t] = _decimals_cache[(chain, t)]
        else:
            missing.append(t)
    for t, res in zip(missing, _calls(chain, [(t, DECIMALS) for t in missing]), strict=True):
        d = _word(res) if res else None
        if d is not None and 0 <= d <= 36:
            _decimals_cache[(chain, t)] = d
            out[t] = d
    return out


def is_v4(pool_address: str) -> bool:
    return len(pool_address) == 66  # 32-byte pool id, not a contract address


@dataclass(frozen=True)
class Quote:
    price: float  # token1 per token0, human units
    inverted_fits: bool  # the feed reports token0 per token1 (we matched 1/price)


def pool_prices(chain: int, pools: list[Pool]) -> dict[str, float]:
    """address → token1-per-token0 price (human units) for every pool we can read."""
    calls: list[tuple[str, str]] = []
    keys: list[str] = []
    for p in pools:
        if is_v4(p.address):
            view = STATE_VIEW.get(chain)
            if not view:
                continue
            calls.append((view, GET_SLOT0 + p.address[2:]))
        else:
            calls.append((p.address, SLOT0))
        keys.append(p.address)
    results = _calls(chain, calls)
    tokens = {t for p in pools for t in (p.token0_addr, p.token1_addr) if t}
    dec = decimals(chain, sorted(tokens)) if tokens else {}
    out: dict[str, float] = {}
    for p, res in zip([q for q in pools if q.address in keys], results, strict=True):
        sqrt = _word(res) if res else None
        if not sqrt:
            continue
        d0 = dec.get(p.token0_addr.lower(), None)
        d1 = dec.get(p.token1_addr.lower(), None)
        if d0 is None or d1 is None:
            continue
        raw = (sqrt / Q96) ** 2
        out[p.address] = raw * 10 ** (d0 - d1)
    return out


def orient(rpc_price: float, feed_price: float | None, tolerance: float = 3.0) -> float | None:
    """Pick `p` or `1/p` to match the feed's orientation; None if neither is plausible.

    Feed and chain can differ by a little (time) but not by orders of magnitude; the
    tolerance is a factor in log space.
    """
    if not rpc_price or rpc_price <= 0:
        return None
    if not feed_price or feed_price <= 0:
        return None
    direct = abs(math.log(rpc_price / feed_price))
    inverse = abs(math.log((1 / rpc_price) / feed_price))
    best = min(direct, inverse)
    if best > math.log(tolerance):
        return None
    return rpc_price if direct <= inverse else 1 / rpc_price


def refresh_prices(chain: int, positions: list[Position], pools: list[Pool]) -> int:
    """Overwrite `current_price` and `status` of open positions with the live pool price.

    Returns how many positions were updated. Positions whose pool is not in `pools`, or
    whose feed price cannot be matched to the chain price, are left as the feed had them.
    """
    by_addr = {p.address: p for p in pools}
    wanted = {}
    for pos in positions:
        if pos.status == "CLOSED":
            continue
        pool = by_addr.get(pos.pool_address) or by_addr.get(pos.pool_alt)
        if pool:
            wanted[pool.address] = pool
    if not wanted:
        return 0
    prices = pool_prices(chain, list(wanted.values()))
    updated = 0
    for pos in positions:
        if pos.status == "CLOSED":
            continue
        pool = by_addr.get(pos.pool_address) or by_addr.get(pos.pool_alt)
        live = prices.get(pool.address) if pool else None
        if live is None:
            continue
        price = orient(live, pos.current_price)
        if price is None:
            continue
        pos.current_price = price
        if pos.min_price > 0 and pos.max_price > pos.min_price:
            pos.status = "IN_RANGE" if pos.min_price <= price <= pos.max_price else "OUT_RANGE"
        updated += 1
    return updated
