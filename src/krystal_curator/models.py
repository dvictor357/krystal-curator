"""Domain model: one row per pool, normalised from the Krystal LP explorer API."""

from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

CHAIN_SLUG: dict[int, str] = {
    1: "ethereum",
    10: "optimism",
    56: "bsc",
    137: "polygon",
    999: "hyperevm",
    2020: "ronin",
    4663: "robinhood",
    8453: "base",
    42161: "arbitrum",
    43114: "avalanche",
}

ROBINHOOD = 4663


def fnum(x: Any, default: float = 0.0) -> float:
    if x in (None, ""):
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


@dataclass(slots=True, frozen=True)
class Stat:
    """Volume / fee / APR for one window. USD, APR in percent."""

    volume: float = 0.0
    fee: float = 0.0
    apr: float = 0.0

    @classmethod
    def parse(cls, d: dict | None) -> Stat:
        d = d or {}
        return cls(
            volume=fnum(d.get("volumeUsd", d.get("volume"))),
            fee=fnum(d.get("feeUsd", d.get("fee"))),
            apr=fnum(d.get("apr")),
        )


@dataclass(slots=True, frozen=True)
class Incentive:
    symbol: str
    daily_usd: float
    apr: float
    killed: bool


@dataclass(slots=True)
class Pool:
    chain_id: int
    protocol: str
    address: str
    token0: str
    token1: str
    fee_tier_pct: float  # already percent in API: 0.35 == 0.35 %
    tvl: float
    s1h: Stat
    s24h: Stat
    s7d: Stat
    s30d: Stat
    drawdown24h: float  # negative percent
    volatility: float  # price volatility, percent
    lp_auto: bool
    dynamic_fee: bool
    tag: str
    incentives: list[Incentive] = field(default_factory=list)
    first_seen_ts: int = 0  # set by the store: first time this tool saw the pool
    token0_addr: str = ""
    token1_addr: str = ""
    token0_logo: str = ""
    token1_logo: str = ""
    tx24: int | None = None  # only filled when Cloud API key present

    # ---- identity -------------------------------------------------------
    @property
    def chain(self) -> str:
        return CHAIN_SLUG.get(self.chain_id, str(self.chain_id))

    @property
    def pair(self) -> str:
        return f"{self.token0}/{self.token1}"

    def has_token(self, symbol: str) -> bool:
        s = symbol.upper()
        return self.token0.upper() == s or self.token1.upper() == s

    def base_vs(self, quote: str) -> str:
        """Token on the other side of `quote`; pair string if quote not in pool."""
        q = quote.upper()
        if self.token0.upper() == q:
            return self.token1
        if self.token1.upper() == q:
            return self.token0
        return self.pair

    @property
    def url(self) -> str:
        q = urllib.parse.urlencode(
            {
                "chainId": self.chain_id,
                "poolAddress": self.address,
                "protocol": self.protocol,
            }
        )
        return f"https://defi.krystal.app/pools/detail?{q}"

    # ---- derived metrics ------------------------------------------------
    @property
    def fee_yield_24h(self) -> float:
        """Fees earned in the last 24h as a fraction of TVL (daily yield)."""
        return self.s24h.fee / self.tvl if self.tvl > 0 else 0.0

    @property
    def fee_yield_7d_daily(self) -> float:
        """Average daily fee yield over the last 7 days."""
        return self.s7d.fee / 7 / self.tvl if self.tvl > 0 else 0.0

    @property
    def turnover_24h(self) -> float:
        """Volume / TVL. >1 means the whole pool traded through in a day."""
        return self.s24h.volume / self.tvl if self.tvl > 0 else 0.0

    @property
    def consistency(self) -> float:
        """fee24h / (fee7d/7). ~1 = steady, >>1 = one-day spike, <<1 = fading."""
        avg = self.s7d.fee / 7
        if avg <= 0:
            return 0.0 if self.s24h.fee <= 0 else 7.0
        return self.s24h.fee / avg

    @property
    def liveness(self) -> float:
        """vol1h * 24 / vol24. 1 = last hour matches daily pace; 0 = dead now."""
        if self.s24h.volume <= 0:
            return 0.0
        return self.s1h.volume * 24 / self.s24h.volume

    @property
    def is_new(self) -> bool:
        """Less than ~1 day of history: 24h and 7d windows are identical."""
        return self.s7d.volume > 0 and abs(self.s7d.volume - self.s24h.volume) < 1e-6

    @property
    def incentive_usd_day(self) -> float:
        return sum(i.daily_usd for i in self.incentives if not i.killed)

    @property
    def incentive_yield_day(self) -> float:
        """Live incentive rewards as a fraction of TVL per day (0 when none / killed)."""
        return self.incentive_usd_day / self.tvl if self.tvl > 0 else 0.0

    @property
    def total_yield_24h(self) -> float:
        return self.fee_yield_24h + self.incentive_yield_day

    @property
    def fee_mismatch(self) -> float | None:
        """(effective − tier) / tier when both are known; >0 = pool charges more than its tier."""
        if self.fee_tier_pct <= 0 or self.s24h.volume < 1000:
            return None
        return (self.effective_fee_pct - self.fee_tier_pct) / self.fee_tier_pct

    @property
    def effective_fee_pct(self) -> float:
        """Realised fee rate: fee24 / vol24. Differs from tier for dynamic-fee pools."""
        return self.s24h.fee / self.s24h.volume * 100 if self.s24h.volume > 0 else 0.0

    @property
    def seen_days(self) -> float | None:
        if not self.first_seen_ts:
            return None
        return (time.time() - self.first_seen_ts) / 86400

    # ---- parsing --------------------------------------------------------
    @classmethod
    def from_public(cls, item: dict) -> Pool:
        t0 = item.get("token0") or {}
        t1 = item.get("token1") or {}
        incentives = [
            Incentive(
                symbol=(i.get("token") or {}).get("symbol", "?"),
                daily_usd=fnum(i.get("dailyRewardUsd")),
                apr=fnum(i.get("apr24h")),
                killed=bool(i.get("isKilled")),
            )
            for i in item.get("incentives") or []
        ]
        return cls(
            chain_id=int(item.get("chainId") or 0),
            protocol=item.get("protocol") or "",
            address=(item.get("poolAddress") or "").lower(),
            token0=t0.get("symbol") or "?",
            token1=t1.get("symbol") or "?",
            token0_addr=(t0.get("address") or "").lower(),
            token1_addr=(t1.get("address") or "").lower(),
            token0_logo=t0.get("logo") or "",
            token1_logo=t1.get("logo") or "",
            fee_tier_pct=fnum(item.get("feeTier")),
            tvl=fnum(item.get("tvlUsd", item.get("tvl"))),
            s1h=Stat.parse(item.get("stat1h")),
            s24h=Stat.parse(item.get("stat24h") or item.get("stats24h")),
            s7d=Stat.parse(item.get("stat7d")),
            s30d=Stat.parse(item.get("stat30d")),
            drawdown24h=fnum(item.get("drawdown24h")),
            volatility=fnum(item.get("priceVolatility")),
            lp_auto=bool(item.get("isSupportLpAuto")),
            dynamic_fee=bool(item.get("dynamicFee")),
            tag=item.get("tag") or "",
            incentives=incentives,
        )
