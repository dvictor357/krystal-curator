"""Read-only tools the agent may call: thin, compact views over the modules that already
exist (`leaderboard`, `vault_review` + `vault_eval`, `api.fetch_pools`, `vaults`). No
tool writes, sends, or spends: no Cloud API, no Telegram, no automation.

Every result is trimmed to what a 16k-context model can use — a full `Review` JSON is
hundreds of kB; `compact_review` is ~5 kB. Fetches are cached per `Toolbox` so the
agent asking twice costs one request, and a caller that already holds a review can
seed it (`Toolbox.seed_review`) so the report path never fetches the same vault twice.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .. import api, leaderboard, vault_eval, vault_review
from ..config import Config
from ..models import Pool
from ..vault_eval import DEFAULT_LIMITS, Evaluation
from ..vault_review import Review
from ..vaults import Vault, fetch_public_vaults, fetch_vaults
from .llm import Tool

INSTRUCTIONS_CHARS = 2500  # the owner's free text, as data


def compact_review(rv: Review, ev: Evaluation) -> dict[str, Any]:
    """What the model needs from a review: the rule verdict with every check, the
    owner's settings (instructions quoted, trimmed), performance, plan stats, fee APR by
    window, open positions and closed series — not the raw payloads."""
    v = rv.vault
    s = rv.settings
    pf = ev.performance
    out: dict[str, Any] = {
        "vault": None
        if v is None
        else {
            "name": v.name,
            "address": v.address,
            "url": v.url,
            "owner": v.owner,
            "age_days": round(v.age_days, 1),
            "tvl": round(v.tvl),
            "pnl": round(v.pnl),
            "fee_apr_pct": round(v.fee_apr),
            "fees_lifetime": round(v.fee_generated),
            "earning_30d": round(v.earning_30d),
            "tx_costs": round(v.max_total_cost),
            "depositors": v.total_users,
            "copied": v.copy_count,
            "risk": v.risk,
            "securities": v.securities,
        },
        "rule_verdict": {"verdict": ev.verdict, "reasons": ev.reasons},
        "checks": [
            {"key": c.key, "result": c.result, "basis": c.basis, "evidence": c.evidence}
            for c in ev.checks
        ],
        "evidence": {"enough": ev.evidence.enough, "why_not": ev.evidence.why_not},
        "performance": {
            "closed_positions": pf.closed_positions,
            "closed_series": pf.closed_series,
            "closed_pnl": round(pf.closed_pnl),
            "closed_fees": round(pf.closed_fees),
            "closed_price_pnl": round(pf.closed_price_pnl),
            "closed_tx_costs": round(pf.closed_tx_costs),
            "closed_pnl_after_tx": round(pf.closed_pnl_after_tx),
            "series_win_rate": pf.series_win_rate,
            "fees_cover_price_moves": pf.fees_cover_price_moves,
            "open_positions": pf.open_positions,
            "open_value": round(pf.open_value),
            "open_pnl": round(pf.open_pnl),
            "largest_position_share": pf.largest_position_share,
            "fee_apr_rederived_pct": {
                k: None if x is None else round(x) for k, x in pf.fee_apr_rederived.items()
            },
            "fee_stability": pf.fee_stability,
        },
        "settings": None
        if s is None
        else {
            "goal": s.goal[:400],
            "instructions": s.instructions[:INSTRUCTIONS_CHARS],
            "permissions": s.permissions,
            "minimum_range_pct": s.minimum_range_pct,
            "minimum_tvl": s.minimum_tvl,
            "whitelisted_pools": len(s.whitelisted_pools),
            "risk_level": s.risk_level,
            "farming_style": s.farming_style,
            "execution": {
                "interval_s": s.execution.interval_s,
                "max_value_per_strategy": s.execution.max_value_per_strategy_text,
                "swap_slippage": s.execution.swap_slippage,
            },
        },
        "plans": None
        if rv.plan_stats is None
        else {
            "fetched": rv.plan_stats.fetched,
            "total": rv.plan_stats.total,
            "by_status": rv.plan_stats.by_status,
            "by_action": rv.plan_stats.by_action,
            "top_errors": dict(list(rv.plan_stats.errors.items())[:5]),
        },
        "open": [
            {
                "pair": p.pair,
                "protocol": p.protocol,
                "value": round(p.value),
                "pnl": round(p.pnl),
                "in_range": p.in_range,
                "range_width_pct": round(p.range_width_pct, 1),
                "age_days": round(p.age_days, 1),
            }
            for p in (v.positions if v else [])[:12]
        ],
        "closed_by_pair": _closed_by_pair(v),
        "missing": rv.missing,
        "sources_failed": [k for k, val in rv.served.items() if val != "ok"],
    }
    return out


def _closed_by_pair(v: Vault | None) -> list[dict[str, Any]]:
    if v is None:
        return []
    by: dict[str, list] = {}
    for p in v.closed:
        by.setdefault(p.pair, []).append(p)
    rows = [
        {
            "pair": pair,
            "positions": len(ps),
            "pnl": round(sum(p.pnl for p in ps)),
            "fees": round(sum(p.fees_total for p in ps)),
            "hold_days": round(sum(p.age_days for p in ps), 1),
        }
        for pair, ps in by.items()
    ]
    rows.sort(key=lambda r: r["pnl"])
    return rows[:15]


def compact_pool(p: Pool) -> dict[str, Any]:
    return {
        "pair": p.pair,
        "protocol": p.protocol,
        "address": p.address,
        "fee_tier_pct": p.fee_tier_pct,
        "tvl": round(p.tvl),
        "volume_24h": round(p.s24h.volume),
        "fees_24h": round(p.s24h.fee),
        "fee_yield_24h_pct": round(p.fee_yield_24h * 100, 3),
        "turnover_24h": round(p.turnover_24h, 2),
        "consistency": round(p.consistency, 2),
        "volatility_pct": None if "volatility" in p.unknown else p.volatility,
        "drawdown_24h_pct": None if "drawdown" in p.unknown else p.drawdown24h,
        "url": p.url,
    }


class Toolbox:
    def __init__(
        self, cfg: Config, *, chain_id: int | None = None, wallet: str | None = None
    ) -> None:
        self.cfg = cfg
        self.chain_id = chain_id or cfg.chain
        self.wallet = wallet if wallet is not None else (cfg.wallet or api.wallet() or "")
        self._public: list[Vault] | None = None
        self._pools: list[Pool] | None = None
        self.reviews: dict[str, tuple[Review, Evaluation]] = {}

    # ---- caches ---------------------------------------------------------
    def seed_review(self, rv: Review, ev: Evaluation) -> None:
        self.reviews[rv.address.lower()] = (rv, ev)

    def review(self, address: str) -> tuple[Review, Evaluation]:
        key = address.lower()
        if key not in self.reviews:
            rv = vault_review.fetch_review(self.chain_id, key)
            self.reviews[key] = (rv, vault_eval.evaluate(rv))
        return self.reviews[key]

    def public_vaults(self) -> list[Vault]:
        if self._public is None:
            self._public = fetch_public_vaults(self.chain_id)
        return self._public

    def pools(self) -> list[Pool]:
        if self._pools is None:
            self._pools = api.fetch_pools(self.chain_id, **self.cfg.fetch_kwargs)
        return self._pools

    # ---- tools ----------------------------------------------------------
    def t_limits(self) -> dict[str, Any]:
        d = asdict(DEFAULT_LIMITS)
        d["protocols"] = sorted(DEFAULT_LIMITS.protocols)
        d["note"] = (
            "platform = a setting Krystal enforces (permissions, restrictions, execution); "
            "a fail there cannot be fixed by rewriting the owner's instructions"
        )
        return d

    def t_leaderboard(
        self, sort: str = "roi", candidates_only: bool = True, top: int = 15
    ) -> dict[str, Any]:
        board = leaderboard.rank(
            self.public_vaults(), sort=sort if sort in leaderboard.SORTS else "roi"
        )
        rows = board.candidates if candidates_only else board.vaults
        return {
            "total_vaults": board.total,
            "copy_candidates": len(board.candidates),
            "sort": board.sort,
            "vaults": [
                {
                    "name": r.vault.name[:32],
                    "address": r.vault.address,
                    "owner": r.vault.owner_name or leaderboard.short(r.vault.owner),
                    "age_days": round(r.vault.age_days),
                    "tvl": round(r.vault.tvl),
                    "pnl": round(r.vault.pnl),
                    "roi_pct": round(r.roi_pct, 1),
                    "roi_annualised_pct": None if r.roi_ann_pct is None else round(r.roi_ann_pct),
                    "fee_apr_pct": round(r.vault.fee_apr),
                    "tx_cost_share": None if r.cost_share is None else round(r.cost_share, 2),
                    "copied": r.vault.copy_count,
                    "candidate": r.candidate,
                    "why_not": r.why_not,
                }
                for r in rows[: max(1, min(int(top), 40))]
            ],
        }

    def t_vault_review(self, address: str) -> dict[str, Any]:
        rv, ev = self.review(address)
        return compact_review(rv, ev)

    def t_pool(self, query: str) -> dict[str, Any]:
        q = query.lower().strip()
        hits = [
            p
            for p in self.pools()
            if p.address.lower() == q
            or q in p.pair.lower()
            or q.replace("/", "") in p.pair.lower().replace("/", "")
        ]
        hits.sort(key=lambda p: p.tvl, reverse=True)
        return {"matches": [compact_pool(p) for p in hits[:8]], "pools_on_feed": len(self.pools())}

    def t_my_positions(self) -> dict[str, Any]:
        if not self.wallet:
            return {"error": "no wallet configured (KRYSTAL_WALLET)"}
        vaults = fetch_vaults(self.wallet, chain_id=self.chain_id)
        return {
            "vaults": [
                {
                    "name": v.name,
                    "owned": v.owned,
                    "tvl": round(v.tvl),
                    "pnl": round(v.pnl),
                    "apr_pct": round(v.apr),
                    "open": [
                        {
                            "pair": p.pair,
                            "value": round(p.value),
                            "pnl": round(p.pnl),
                            "in_range": p.in_range,
                            "range_width_pct": round(p.range_width_pct, 1),
                        }
                        for p in v.positions
                    ],
                    "closed": len(v.closed),
                }
                for v in vaults
            ]
        }

    def tools(self) -> list[Tool]:
        return [
            Tool(
                "limits",
                "our risk limits as numbers, with what 'platform' means",
                {},
                self.t_limits,
            ),
            Tool(
                "leaderboard",
                "public AutoFarm vaults on the chain, ranked; candidates_only=false shows the rest with why_not",
                {
                    "sort": {"type": "string", "enum": list(leaderboard.SORTS)},
                    "candidates_only": {"type": "boolean"},
                    "top": {"type": "integer", "minimum": 1, "maximum": 40},
                },
                self.t_leaderboard,
            ),
            Tool(
                "vault_review",
                "full review of one vault by address: rule verdict, checks, owner settings and instructions, performance, plans, positions",
                {"address": {"type": "string", "pattern": "^0x[0-9a-fA-F]{40}$"}},
                self.t_vault_review,
                required=["address"],
            ),
            Tool(
                "pool",
                "pools on the feed matching a pair like ETH/USDG or an address: TVL, volume, fees, yield, volatility",
                {"query": {"type": "string", "minLength": 2}},
                self.t_pool,
                required=["query"],
            ),
            Tool(
                "my_positions",
                "the configured wallet's vaults and open positions",
                {},
                self.t_my_positions,
            ),
        ]
