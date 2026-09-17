"""Who is actually making money with public AutoFarm vaults, and which vaults are worth
copying. Pure ranking over the public vault list (`vaults.fetch_public_vaults`); the
per-vault verdict is `vault_review` + `vault_eval`, run on the shortlist, not repeated here.

Profit is measured on capital, not in dollars: `pnl / deposited`, where deposited is the
vault's lifetime deposits (`userPerformance.totalDepositValue`, the aggregate of every
depositor on the public list). Re-deposits inflate that denominator, so ROI is a floor
on churny vaults. Annualised by age so a 20-day vault and a 200-day one rank on the
same footing; the age floor keeps 3-day wonders out. `pnl` is taken as the feed serves
it: it does not reconcile with value + withdrawn − deposited, so its exact netting
(costs? pending fees?) is unknown and every number here is a comparison, not a P&L.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .vault_eval import DEFAULT_LIMITS, Limits
from .vaults import Vault

SORTS = ("roi", "pnl", "apr", "30d")
MIN_TVL = 500.0  # below this a vault is a test balance, not a track record
MAX_COST_SHARE = 0.5  # transaction costs above half of fees generated: the agent churns


@dataclass(slots=True)
class VaultRank:
    vault: Vault
    deposited: float  # lifetime deposits, else TVL when the feed served none
    roi_pct: float  # pnl / deposited
    roi_ann_pct: float | None  # roi × 365 / age; None when age is unknown
    yield_30d_pct: float | None  # earning30d / tvl; None when TVL is 0
    cost_share: float | None  # maxTotalCost / feeGenerated; None when no fees
    why_not: list[str] = field(default_factory=list)  # empty ⇒ copy candidate

    @property
    def candidate(self) -> bool:
        return not self.why_not


@dataclass(slots=True)
class OwnerRank:
    address: str
    name: str
    verified: str
    followers: int
    vaults: list[VaultRank]
    pnl: float
    deposited: float
    tvl: float
    fees: float
    earning_30d: float
    copies: int

    @property
    def roi_pct(self) -> float:
        return self.pnl / self.deposited * 100 if self.deposited > 0 else 0.0

    @property
    def best(self) -> VaultRank:
        return max(self.vaults, key=lambda r: r.roi_pct)

    @property
    def label(self) -> str:
        return self.name or f"{self.address[:6]}…{self.address[-4:]}"


@dataclass(slots=True)
class Leaderboard:
    vaults: list[VaultRank]
    owners: list[OwnerRank]
    sort: str
    total: int  # vaults on the feed before any filter

    @property
    def candidates(self) -> list[VaultRank]:
        return [r for r in self.vaults if r.candidate]


def rank_vault(
    v: Vault, *, min_age_days: float = DEFAULT_LIMITS.min_age_days, min_tvl: float = MIN_TVL
) -> VaultRank:
    deposited = v.my_deposit if v.my_deposit > 0 else v.tvl
    roi = v.pnl / deposited * 100 if deposited > 0 else 0.0
    r = VaultRank(
        vault=v,
        deposited=deposited,
        roi_pct=roi,
        roi_ann_pct=roi * 365 / v.age_days if v.age_days > 0 else None,
        yield_30d_pct=v.earning_30d / v.tvl * 100 if v.tvl > 0 else None,
        cost_share=v.max_total_cost / v.fee_generated if v.fee_generated > 0 else None,
    )
    if v.age_days < min_age_days:
        r.why_not.append(f"age {v.age_days:.0f}d < {min_age_days:g}d")
    if v.tvl < min_tvl:
        r.why_not.append(f"tvl {v.tvl:,.0f} < {min_tvl:,.0f}")
    if v.pnl <= 0:
        r.why_not.append(f"pnl {v.pnl:+,.0f}")
    if v.fee_generated <= 0:
        r.why_not.append("no fees")
    elif r.cost_share is not None and r.cost_share > MAX_COST_SHARE:
        r.why_not.append(f"tx costs {r.cost_share * 100:.0f}% of fees")
    if not v.agent_activated:
        r.why_not.append("no agent (nothing to copy)")
    return r


def _sort_key(sort: str):
    if sort == "roi":
        return lambda r: r.roi_ann_pct if r.roi_ann_pct is not None else float("-inf")
    if sort == "pnl":
        return lambda r: r.vault.pnl
    if sort == "apr":
        return lambda r: r.vault.fee_apr
    if sort == "30d":
        return lambda r: r.yield_30d_pct if r.yield_30d_pct is not None else float("-inf")
    raise ValueError(f"sort must be one of {SORTS}, not {sort!r}")


def _owner_key(sort: str):
    if sort == "roi":
        return lambda o: o.roi_pct
    if sort == "pnl":
        return lambda o: o.pnl
    if sort == "apr":
        return lambda o: max(r.vault.fee_apr for r in o.vaults)
    return lambda o: o.earning_30d / o.tvl if o.tvl > 0 else float("-inf")


def rank(
    vaults: list[Vault],
    *,
    sort: str = "roi",
    lim: Limits = DEFAULT_LIMITS,
    min_tvl: float = MIN_TVL,
) -> Leaderboard:
    """Rank every vault and every owner. Copy candidates come first, then the rest, each
    group in sort order, so a 3-day vault with a 2,000 % annualised ROI does not sit on
    top of the table with its reason next to it. Owners aggregate all of their vaults
    (a loser vault counts) and need `min_tvl` of lifetime deposits to be ranked at all:
    a 100 $ test balance with +60 % is not a track record.
    """
    key = _sort_key(sort)
    ranked = sorted(
        (rank_vault(v, min_age_days=lim.min_age_days, min_tvl=min_tvl) for v in vaults),
        key=lambda r: (r.candidate, key(r)),
        reverse=True,
    )
    by_owner: dict[str, list[VaultRank]] = defaultdict(list)
    for r in ranked:
        if r.vault.owner:
            by_owner[r.vault.owner].append(r)
    owners = [
        OwnerRank(
            address=addr,
            name=next((r.vault.owner_name for r in rs if r.vault.owner_name), ""),
            verified=next((r.vault.owner_verified for r in rs if r.vault.owner_verified), ""),
            followers=max(r.vault.owner_followers for r in rs),
            vaults=rs,
            pnl=sum(r.vault.pnl for r in rs),
            deposited=sum(r.deposited for r in rs),
            tvl=sum(r.vault.tvl for r in rs),
            fees=sum(r.vault.fee_generated for r in rs),
            earning_30d=sum(r.vault.earning_30d for r in rs),
            copies=sum(r.vault.copy_count for r in rs),
        )
        for addr, rs in by_owner.items()
    ]
    owners = [o for o in owners if o.deposited >= min_tvl]
    owners.sort(key=_owner_key(sort), reverse=True)
    return Leaderboard(vaults=ranked, owners=owners, sort=sort, total=len(vaults))
