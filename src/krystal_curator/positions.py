"""Your live LP positions via Krystal Cloud (KC-APIKey, 10 units per call)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import net
from .api import _HEADERS, CLOUD_BASE, KrystalError
from .models import fnum

POSITIONS_UNITS = 10


@dataclass(slots=True)
class Position:
    id: str
    chain_id: int
    pool_address: str
    protocol: str  # protocol key when known, else display name
    token0: str
    token1: str
    status: str  # IN_RANGE / OUT_RANGE / CLOSED
    value: float
    deposit: float
    withdrawn: float
    pnl: float
    roi_pct: float
    il: float
    fee_pending: float
    fee_claimed: float
    reward_pending: float
    fee_apr: float
    total_apr: float
    min_price: float
    max_price: float
    current_price: float | None
    opened_ts: int
    amounts: list[tuple[str, float]] = field(default_factory=list)  # (symbol, usd)
    vault: str = ""  # vault name when the position lives inside a Krystal vault
    pool_alt: str = ""  # alternate pool key (v4: contract address next to the pool id)
    fee_tier: float = 0.0  # percent
    cost: float = 0.0  # transaction costs spent on the position, USD (vault `maxTotalCost`)

    @property
    def pair(self) -> str:
        return f"{self.token0}/{self.token1}"

    @property
    def in_range(self) -> bool:
        return self.status == "IN_RANGE"

    @property
    def age_days(self) -> float:
        return (time.time() - self.opened_ts) / 86400 if self.opened_ts else 0.0

    @property
    def fees_total(self) -> float:
        return self.fee_pending + self.fee_claimed

    @property
    def range_pos(self) -> float | None:
        """Where the current price sits inside [min, max]: 0 = at min, 1 = at max."""
        if self.current_price is None or self.max_price <= self.min_price:
            return None
        return (self.current_price - self.min_price) / (self.max_price - self.min_price)

    @property
    def range_width_pct(self) -> float:
        """Half-width of the range as % of its geometric centre."""
        if self.min_price <= 0 or self.max_price <= 0:
            return 0.0
        mid = (self.min_price * self.max_price) ** 0.5
        return (self.max_price / mid - 1) * 100


def _usd_list(items: list | None) -> tuple[float, list[tuple[str, float]]]:
    total, out = 0.0, []
    for x in items or []:
        v = fnum(x.get("value"))
        total += v
        out.append(((x.get("token") or {}).get("symbol") or "?", v))
    return total, out


def parse_position(d: dict) -> Position:
    chain = d.get("chain") or {}
    pool = d.get("pool") or {}
    proto = pool.get("protocol") or {}
    perf = d.get("performance") or {}
    apr = perf.get("apr") or {}
    fee = d.get("tradingFee") or {}
    farm = d.get("farmingReward") or {}
    cur_val, cur = _usd_list(d.get("currentAmounts"))
    syms = [s for s, _ in cur] or [s for s, _ in _usd_list(d.get("providedAmounts"))[1]]
    t0 = syms[0] if syms else "?"
    t1 = syms[1] if len(syms) > 1 else "?"
    # token1 price in token0 terms when both current amounts carry prices
    cur_price = None
    prices = [fnum(x.get("price")) for x in d.get("currentAmounts") or []]
    if len(prices) == 2 and prices[0] > 0 and prices[1] > 0:
        cur_price = prices[0] / prices[1]
    return Position(
        id=d.get("id") or "",
        chain_id=int(chain.get("id") or d.get("chainId") or 0),
        pool_address=(pool.get("poolAddress") or pool.get("id") or "").lower(),
        protocol=proto.get("key") or proto.get("name") or "",
        token0=t0,
        token1=t1,
        status=d.get("status") or "",
        value=fnum(d.get("currentPositionValue")) or cur_val,
        deposit=fnum(perf.get("totalDepositValue")),
        withdrawn=fnum(perf.get("totalWithdrawValue")),
        pnl=fnum(perf.get("pnl")),
        roi_pct=fnum(perf.get("returnOnInvestment")),
        il=fnum(perf.get("impermanentLoss")),
        fee_pending=_usd_list(fee.get("pending"))[0],
        fee_claimed=_usd_list(fee.get("claimed"))[0],
        reward_pending=_usd_list(farm.get("pending"))[0],
        fee_apr=fnum(apr.get("feeApr")),
        total_apr=fnum(apr.get("totalApr")),
        min_price=fnum(d.get("minPrice")),
        max_price=fnum(d.get("maxPrice")),
        current_price=cur_price,
        opened_ts=int(d.get("openedTime") or 0),
        amounts=cur,
    )


def fetch_positions(
    key: str,
    wallet: str,
    *,
    chain_ids: list[int] | None = None,
    status: str = "OPEN",
    timeout: float = 30.0,
) -> list[Position]:
    params: dict = {"wallet": wallet, "positionStatus": status, "limit": 500}
    if chain_ids:
        params["chainIds"] = ",".join(str(c) for c in chain_ids)
    net.register_secret(key)
    try:
        r = net.get(
            f"{CLOUD_BASE}/positions",
            params=params,
            headers={**_HEADERS, "KC-APIKey": key},
            timeout=timeout,
        )
        if r.status_code == 401:
            raise KrystalError("Cloud API: invalid KC-APIKey (401)")
        if r.status_code == 402:
            raise KrystalError("Cloud API: no units left (402) — top up at cloud.krystal.app")
        if r.status_code != 200:
            raise net.status_error(r, f"positions {wallet[:8]}…")
        data = r.json()
    except (net.HttpError, ValueError) as e:
        raise KrystalError(f"positions {wallet[:8]}…: {e}") from None
    rows = data
    if isinstance(data, dict):
        rows = data.get("positions") or data.get("data") or data.get("result") or []
    if not isinstance(rows, list):
        raise KrystalError(f"positions: unexpected payload {type(data).__name__}")
    return [parse_position(x) for x in rows]
