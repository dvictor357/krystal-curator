"""Krystal vaults (public API, no key): the vaults a wallet owns or joined and the LP
positions ("strategies") inside them. This is where an auto-farm / vault manager's
positions live — the wallet itself holds vault shares, not the LP NFTs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import net
from .api import _HEADERS, KrystalError
from .models import fnum
from .positions import Position

VAULTS = "https://api.krystal.app/all/v1/vaults"


@dataclass(slots=True)
class Vault:
    chain_id: int
    address: str
    name: str
    vault_type: str  # autofarm / vaultx / ...
    owned: bool
    tvl: float
    pnl: float
    apr: float
    fee_generated: float
    earning_24h: float
    earning_30d: float
    risk: str
    age_days: float
    my_value: float
    my_deposit: float
    my_withdrawn: float
    positions: list[Position] = field(default_factory=list)
    closed: list[Position] = field(default_factory=list)
    # public-vault facts (detail endpoint), unknown → "" / False / 0.0
    owner: str = ""
    total_users: int = 0
    allow_deposit: bool = False
    agent_activated: bool = False
    securities: list[str] = field(default_factory=list)  # vaultSecurities[].value
    max_total_cost: float = 0.0  # `maxTotalCost` as served; semantics unverified
    min_pnl: float = 0.0  # `minPnl` as served; semantics unverified

    @property
    def url(self) -> str:
        return f"https://defi.krystal.app/vaults/{self.chain_id}/{self.address}"

    @property
    def closed_pnl(self) -> float:
        return sum(p.pnl for p in self.closed)

    @property
    def win_rate(self) -> float | None:
        if not self.closed:
            return None
        return sum(1 for p in self.closed if p.pnl > 0) / len(self.closed)


def _get(url: str, params: dict | None = None) -> dict | list:
    try:
        r = net.get(url, params=params, headers=_HEADERS, timeout=30)
        if r.status_code != 200:
            raise net.status_error(r, "vaults")
        return r.json()
    except (net.HttpError, ValueError) as e:
        raise KrystalError(f"vaults: {e}") from None


def _parse_vault(d: dict, *, owned: bool) -> Vault:
    up = d.get("userPerformance") or {}
    return Vault(
        chain_id=int(d.get("chainId") or 0),
        address=(d.get("vaultAddress") or "").lower(),
        name=d.get("name") or "?",
        vault_type=d.get("vaultType") or "",
        owned=owned,
        tvl=fnum(d.get("tvl")),
        pnl=fnum(d.get("pnl")),
        apr=fnum(d.get("apr")),
        fee_generated=fnum(d.get("feeGenerated")),
        earning_24h=fnum(d.get("earning24h")),
        earning_30d=fnum(d.get("earning30d")),
        risk=d.get("riskScore") or "",
        age_days=fnum(d.get("ageInSecond")) / 86400,
        my_value=fnum(up.get("value")),
        my_deposit=fnum(up.get("totalDepositValue")),
        my_withdrawn=fnum(up.get("totalWithdrawValue")),
        owner=((d.get("owner") or {}).get("address") or d.get("ownerAddress") or "").lower(),
        total_users=int(d.get("totalUser") or 0),
        allow_deposit=bool(d.get("allowDeposit")),
        agent_activated=bool(d.get("isAgentActivated")),
        securities=[x.get("value") for x in d.get("vaultSecurities") or [] if x.get("value")],
        max_total_cost=fnum(d.get("maxTotalCost")),
        min_pnl=fnum(d.get("minPnl")),
    )


def parse_strategy(s: dict, vault_name: str) -> Position:
    toks = s.get("tokens") or []
    t0 = (toks[0].get("symbol") if toks else None) or "?"
    t1 = (toks[1].get("symbol") if len(toks) > 1 else None) or "?"
    pool = s.get("pool") or {}
    proto = s.get("protocol") or {}
    pending = sum(
        fnum(((x.get("quotes") or {}).get("usd") or {}).get("value"))
        for x in s.get("feesPending") or []
    )
    age = fnum(s.get("ageInSecond"))
    return Position(
        id=f"{vault_name}:{s.get('strategyId')}",
        chain_id=int(s.get("chainId") or 0),
        # v4 pools are keyed by their 32-byte id in the LP explorer, v2/v3 by address
        pool_address=(pool.get("id") or pool.get("poolAddress") or "").lower(),
        pool_alt=(pool.get("poolAddress") or "").lower(),
        protocol=proto.get("key") or pool.get("protocol") or "",
        token0=t0,
        token1=t1,
        status=s.get("status") or "",
        value=fnum(s.get("lpValue")),
        deposit=fnum(s.get("initialDepositValue")),
        withdrawn=0.0,
        pnl=fnum(s.get("pnl")),
        roi_pct=fnum(s.get("roi")),
        il=0.0,
        # feeGenerated is lifetime fees including what is still pending
        fee_pending=pending,
        fee_claimed=max(0.0, fnum(s.get("feeGenerated")) - pending),
        reward_pending=fnum(s.get("farmRewardPending")),
        fee_apr=fnum(s.get("apr")),
        total_apr=fnum(s.get("apr")),
        min_price=fnum(s.get("minPrice")),
        max_price=fnum(s.get("maxPrice")),
        current_price=fnum(s.get("currentPoolPrice")) or None,
        opened_ts=int(time.time() - age) if age else 0,
        amounts=[],
        vault=vault_name,
        fee_tier=fnum(s.get("feeTierPercentage")) or fnum(pool.get("fee")),
        cost=fnum(s.get("maxTotalCost")),
    )


def fetch_vault(chain_id: int, address: str) -> Vault:
    """One vault by address, with its open and closed strategies. No wallet needed:
    the detail endpoint is public, so `userPerformance` (if any) is the owner's, not ours.
    """
    detail = _get(f"{VAULTS}/{chain_id}/{address.lower()}")
    if not isinstance(detail, dict) or not detail.get("vaultAddress"):
        raise KrystalError(f"vaults: no vault {address} on chain {chain_id}")
    v = _parse_vault(detail, owned=False)
    _attach_strategies(v, detail)
    return v


def _attach_strategies(v: Vault, detail: dict) -> None:
    for s in detail.get("strategies") or []:
        p = parse_strategy(s, v.name)
        (v.closed if p.status == "CLOSED" else v.positions).append(p)


def fetch_vaults(wallet: str, *, chain_id: int | None = None) -> list[Vault]:
    """Owned (both auto-farm and regular) plus joined vaults, with their positions."""
    seen: dict[str, Vault] = {}
    queries = [
        ({"ownerAddress": wallet, "isAutoFarmVault": "true", "perPage": 100}, True),
        ({"ownerAddress": wallet, "isAutoFarmVault": "false", "perPage": 100}, True),
        ({"userAddress": wallet, "perPage": 100}, False),
        ({"userAddress": wallet, "isAutoFarmVault": "true", "perPage": 100}, False),
    ]
    for params, owned in queries:
        data = _get(f"{VAULTS}/profile", params)
        for d in (data.get("data") if isinstance(data, dict) else None) or []:
            v = _parse_vault(d, owned=owned)
            if chain_id and v.chain_id != chain_id:
                continue
            if v.address in seen:
                seen[v.address].owned |= owned
                continue
            seen[v.address] = v
    for v in seen.values():
        detail = _get(f"{VAULTS}/{v.chain_id}/{v.address}")
        if isinstance(detail, dict):
            _attach_strategies(v, detail)
    return sorted(seen.values(), key=lambda v: v.tvl, reverse=True)
