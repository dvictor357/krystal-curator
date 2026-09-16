"""Review one public AutoFarm vault from its URL: what it holds, how its agent is
configured, what the agent has been doing, and how the numbers line up.

Everything here is deterministic and read-only. Four public endpoints, no wallet, no
key, no LLM:

- `api.krystal.app/all/v1/vaults/{chain}/{address}`            summary + strategies
- `ai-agent-api.krystal.app/public-api/vault-agent-settings`   goal, instructions,
  permissions, restrictions, execution settings
- `ai-agent-api.krystal.app/public-api/auto-farming-action-plans`  paginated history
  of what the agent decided and whether it executed
- `api.krystal.app/all/v1/vaults/performance/{chain}/{address}?timeframe=`  TVL /
  fee series per bucket

The result is a dated snapshot with provenance: which endpoints answered, what is
missing, what cannot be verified from public data. A metric a feed did not serve
stays unknown; it is never written as zero. The vault's `instructions` are another
user's free text: they are quoted for the reader, never interpreted as commands.

Observations are facts about the source (exit not permitted, range floor 5 %, …),
not a verdict — that is the evaluation stage, once these numbers are trusted.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from . import net
from .analytics import TrackRecord, track_record
from .api import _HEADERS, KrystalError
from .models import fnum
from .vaults import Vault, fetch_vault


class Evaluation(Protocol):
    def to_markdown(self) -> str: ...
    def to_dict(self) -> dict: ...


AGENT_API = "https://ai-agent-api.krystal.app/public-api"
PERF_API = "https://api.krystal.app/all/v1/vaults/performance"
VAULT_HOSTS = frozenset({"defi.krystal.app", "www.defi.krystal.app"})
TIMEFRAMES = ("24h", "7d", "30d")
PLANS_PAGE = 100

# Our own hard limits, used only to label observations here (the adaptation stage
# enforces them). Total range width, not half-width.
OUR_MIN_RANGE_TOTAL_PCT = 20.0
OUR_QUOTE = "USDG"

_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class VaultUrlError(ValueError):
    pass


def parse_vault_url(text: str) -> tuple[int, str]:
    """`https://defi.krystal.app/vaults/<chain>/<address>[?…]` or `<chain>/<address>`."""
    text = text.strip()
    if "://" in text:
        u = urlparse(text)
        if u.scheme != "https" or u.hostname not in VAULT_HOSTS:
            raise VaultUrlError(f"not a Krystal vault URL: {text}")
        parts = [p for p in u.path.split("/") if p]
        if len(parts) != 3 or parts[0] != "vaults":
            raise VaultUrlError(f"expected /vaults/<chain>/<address>: {u.path}")
        chain_s, addr = parts[1], parts[2]
    else:
        chain_s, _, addr = text.partition("/")
    if not chain_s.isdigit():
        raise VaultUrlError(f"chain id must be an integer: {chain_s!r}")
    if not _ADDR_RE.match(addr):
        raise VaultUrlError(f"vault address must be 0x + 40 hex chars: {addr!r}")
    return int(chain_s), addr.lower()


# ---- agent settings ----------------------------------------------------------


@dataclass(slots=True)
class Execution:
    interval_s: float | None = None
    swap_slippage: float | None = None  # fraction (0.02 = 2 %)
    liquidity_slippage: float | None = None
    withdraw_slippage: float | None = None
    max_gas_fee_ceiling: float | None = None
    max_gas_fee_ceiling_unit: str = ""
    max_value_per_strategy: float | None = None  # served as a fraction when unit is "%"
    max_value_per_strategy_unit: str = ""

    @property
    def max_value_per_strategy_text(self) -> str:
        x = self.max_value_per_strategy
        if x is None:
            return "unknown"
        if self.max_value_per_strategy_unit == "%":
            return f"{x * 100:g}% of TVL"  # verified: cap 302$ on a ~2,015$ vault at 0.15
        return f"{x:g}{self.max_value_per_strategy_unit}"

    strict_max_value_per_strategy: bool | None = None


@dataclass(slots=True)
class Settings:
    goal: str = ""
    instructions: str = ""  # untrusted free text from the vault owner
    enabled: bool | None = None
    need_confirm: bool | None = None
    permissions: list[str] = field(default_factory=list)
    minimum_range_pct: float | None = None  # platform restriction, total width
    minimum_tvl: float | None = None
    whitelisted_pools: list[str] = field(default_factory=list)
    target_token_type: str = ""
    risk_level: str = ""
    farming_style: str = ""
    expected_return: str = ""
    last_triggered_at: str | None = None
    execution: Execution = field(default_factory=Execution)


def _opt(x) -> float | None:
    return None if x in (None, "") else fnum(x)


def parse_settings(d: dict) -> Settings:
    cfg = d.get("autoFarmingConfig") or {}
    ex = cfg.get("executionConfig") or {}
    rs = cfg.get("restrictions") or {}
    vc = d.get("vaultConfig") or {}
    interval = _opt(ex.get("interval"))
    return Settings(
        goal=str(d.get("goal") or ""),
        instructions=str(cfg.get("instructions") or ""),
        enabled=None if cfg.get("enabled") is None else bool(cfg.get("enabled")),
        need_confirm=None if cfg.get("isNeedToConfirm") is None else bool(cfg["isNeedToConfirm"]),
        permissions=[str(p) for p in cfg.get("permissions") or []],
        minimum_range_pct=_opt(rs.get("minimumRange")),
        minimum_tvl=_opt(rs.get("minimumTvl")),
        whitelisted_pools=[str(p).lower() for p in rs.get("whitelistedPools") or []],
        target_token_type=str(cfg.get("targetTokenType") or ""),
        risk_level=str(vc.get("riskLevel") or ""),
        farming_style=str(vc.get("farmingStyle") or ""),
        expected_return=str(vc.get("expectedReturn") or ""),
        last_triggered_at=d.get("lastTriggeredAt"),
        execution=Execution(
            interval_s=interval / 1000 if interval is not None else None,  # served in ms
            swap_slippage=_opt(ex.get("swapSlippage")),
            liquidity_slippage=_opt(ex.get("liquiditySlippage")),
            withdraw_slippage=_opt(ex.get("withdrawSlippage")),
            max_gas_fee_ceiling=_opt(ex.get("maxGasFeeCeiling")),
            max_gas_fee_ceiling_unit=str(ex.get("maxGasFeeCeilingUnit") or ""),
            max_value_per_strategy=_opt(ex.get("maxValuePerStrategy")),
            max_value_per_strategy_unit=str(ex.get("maxValuePerStrategyUnit") or ""),
            strict_max_value_per_strategy=(
                None
                if ex.get("strictMaxValuePerStrategy") is None
                else bool(ex["strictMaxValuePerStrategy"])
            ),
        ),
    )


# ---- action plans --------------------------------------------------------------


@dataclass(slots=True)
class PlanResult:
    action: str
    status: str  # onChainStatus, or "" when the action never got a tx
    error: str
    tx: str


@dataclass(slots=True)
class Plan:
    id: str
    status: str  # success / partial_success / failed / …
    created_at: str
    actions: list[str]
    scenarios: list[str]
    results: list[PlanResult]


@dataclass(slots=True)
class PlanStats:
    total: int | None = None  # pagination.total as served
    fetched: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_action: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)  # error text (trimmed) → count
    newest: str = ""
    oldest: str = ""

    @property
    def failure_rate(self) -> float | None:
        if not self.fetched:
            return None
        return self.by_status.get("failed", 0) / self.fetched


def parse_plan(d: dict) -> Plan:
    actions = d.get("actions") or []
    results = ((d.get("executionResult") or {}).get("results")) or []
    return Plan(
        id=str(d.get("id") or ""),
        status=str(d.get("status") or ""),
        created_at=str(d.get("createdAt") or ""),
        actions=[str(a.get("action") or "") for a in actions],
        scenarios=[str(a.get("scenario") or "") for a in actions],
        results=[
            PlanResult(
                action=str(r.get("action") or ""),
                status=str(r.get("onChainStatus") or ""),
                error=str(r.get("error") or ""),
                tx=str(r.get("txHash") or ""),
            )
            for r in results
        ],
    )


def _error_key(text: str) -> str:
    """Collapse an error line to its stable prefix so the same failure counts once."""
    t = re.sub(r"\$?\d[\d.,]*", "N", text.strip())
    return t[:80]


def plan_stats(plans: list[Plan], total: int | None) -> PlanStats:
    st = PlanStats(total=total, fetched=len(plans))
    st.by_status = dict(Counter(p.status for p in plans))
    st.by_action = dict(Counter(a for p in plans for a in p.actions))
    st.errors = dict(
        Counter(_error_key(r.error) for p in plans for r in p.results if r.error).most_common(8)
    )
    stamps = sorted(p.created_at for p in plans if p.created_at)
    if stamps:
        st.oldest, st.newest = stamps[0], stamps[-1]
    return st


# ---- performance series ------------------------------------------------------------


@dataclass(slots=True)
class PerfPoint:
    ts: int
    duration_s: int
    tvl: float
    lp_value: float
    fee_earned: float
    apr: float
    share_price_usd: float


@dataclass(slots=True)
class PerfSeries:
    timeframe: str
    points: list[PerfPoint]

    @property
    def fee_sum(self) -> float:
        return sum(p.fee_earned for p in self.points)

    @property
    def span_s(self) -> int:
        return sum(p.duration_s for p in self.points)

    @property
    def avg_tvl(self) -> float | None:
        if not self.points or self.span_s <= 0:
            return None
        return sum(p.tvl * p.duration_s for p in self.points) / self.span_s

    @property
    def fee_apr_pct(self) -> float | None:
        """Fees over the window, annualised on time-weighted TVL. Comparable to a
        banner "APR 7d" but computed from the served buckets, so it can be re-derived."""
        avg = self.avg_tvl
        if avg is None or avg <= 0:
            return None
        return self.fee_sum / avg * (365 * 86400 / self.span_s) * 100

    @property
    def feed_apr_pct(self) -> float | None:
        """The feed's own `apr` in the newest bucket (a fraction: 5.13 = 513 %). On the
        7d window it equals the detail endpoint's `apr`."""
        return self.points[-1].apr * 100 if self.points else None

    @property
    def share_price_known(self) -> bool:
        return any(p.share_price_usd > 0 for p in self.points)


def parse_perf(timeframe: str, d: dict) -> PerfSeries:
    pts = [
        PerfPoint(
            ts=int(fnum(x.get("timestamp"))),
            duration_s=int(fnum(x.get("duration"))),
            tvl=fnum(x.get("tvl")),
            lp_value=fnum(x.get("lpValue")),
            fee_earned=fnum(x.get("feeEarned")),
            apr=fnum(x.get("apr")),
            share_price_usd=fnum(x.get("sharePriceUsd")),
        )
        for x in d.get("data") or []
    ]
    return PerfSeries(timeframe, sorted(pts, key=lambda p: p.ts))


# ---- the snapshot ------------------------------------------------------------------


@dataclass(slots=True)
class Observation:
    key: str
    level: str  # fact / warn
    text: str
    basis: str  # "platform" (enforced control) / "instructions" (free text) / "data"


@dataclass(slots=True)
class Review:
    fetched_at: str
    chain_id: int
    address: str
    url: str
    vault: Vault | None = None
    settings: Settings | None = None
    plans: list[Plan] = field(default_factory=list)
    plan_stats: PlanStats | None = None
    perf: dict[str, PerfSeries] = field(default_factory=dict)
    served: dict[str, str] = field(default_factory=dict)  # endpoint → "ok" / error text
    missing: list[str] = field(default_factory=list)  # what the report cannot state
    observations: list[Observation] = field(default_factory=list)
    raw: dict = field(default_factory=dict)  # verbatim responses, for provenance

    @property
    def track(self) -> TrackRecord:
        return track_record(self.vault.closed if self.vault else [])


def _agent_get(path: str, params: dict) -> dict:
    r = net.get(f"{AGENT_API}/{path}", params=params, headers=_HEADERS, timeout=30)
    if r.status_code != 200:
        raise net.status_error(r, path)
    data = r.json()
    if not isinstance(data, dict):
        raise KrystalError(f"{path}: unexpected payload")
    return data


def fetch_review(
    chain_id: int,
    address: str,
    *,
    plans_limit: int = PLANS_PAGE,
    timeframes: tuple[str, ...] = TIMEFRAMES,
) -> Review:
    """Pull every public source for one vault; a source that fails is recorded, not fatal
    (the detail endpoint excepted: without it there is nothing to review)."""
    address = address.lower()
    rv = Review(
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        chain_id=chain_id,
        address=address,
        url=f"https://defi.krystal.app/vaults/{chain_id}/{address}",
    )
    q = {"chainId": chain_id, "vaultAddress": address}

    rv.vault = fetch_vault(chain_id, address)
    rv.served["detail"] = "ok"

    try:
        raw = _agent_get("vault-agent-settings", q)
        rv.raw["settings"] = raw
        rv.settings = parse_settings(raw)
        rv.served["settings"] = "ok"
    except (net.HttpError, KrystalError, ValueError) as e:
        rv.served["settings"] = net.redact(str(e))
        rv.missing.append("agent settings (goal, instructions, permissions, restrictions)")

    try:
        raw = _agent_get(
            "auto-farming-action-plans", {**q, "offset": 0, "limit": max(1, plans_limit)}
        )
        rows = raw.get("data") or []
        rv.raw["plans"] = {
            "pagination": raw.get("pagination"),
            "data": [{k: v for k, v in r.items() if k != "vaultData"} for r in rows],
        }
        rv.plans = [parse_plan(r) for r in rows]
        total = (raw.get("pagination") or {}).get("total")
        rv.plan_stats = plan_stats(rv.plans, int(total) if total is not None else None)
        rv.served["plans"] = "ok"
        if total is not None and int(total) > len(rows):
            rv.missing.append(f"action plans beyond the newest {len(rows)} of {int(total)}")
    except (net.HttpError, KrystalError, ValueError) as e:
        rv.served["plans"] = net.redact(str(e))
        rv.missing.append("agent action-plan history")

    for tf in timeframes:
        try:
            r = net.get(
                f"{PERF_API}/{chain_id}/{address}",
                params={"timeframe": tf},
                headers=_HEADERS,
                timeout=30,
            )
            if r.status_code != 200:
                raise net.status_error(r, f"performance {tf}")
            raw = r.json()
            rv.raw[f"perf_{tf}"] = raw
            rv.perf[tf] = parse_perf(tf, raw)
            rv.served[f"performance {tf}"] = "ok"
        except (net.HttpError, KrystalError, ValueError) as e:
            rv.served[f"performance {tf}"] = net.redact(str(e))
            rv.missing.append(f"performance series {tf}")

    if not any(s.share_price_known for s in rv.perf.values()):
        rv.missing.append(
            "NAV per share (sharePriceUsd is 0 in every bucket) — drawdown cannot be verified"
        )
    rv.missing.append("costs other than transaction costs (`maxTotalCost`); `minPnl` semantics")
    rv.observations = observe(rv)
    return rv


# ---- observations ------------------------------------------------------------------


def _rebalance_chains(v: Vault) -> list[tuple[str, int]]:
    """Closed positions on the same pair: a rebalance / re-entry series, not independent
    trades (the same pair on another fee tier is still the same bet)."""
    counts = Counter(p.pair for p in v.closed)
    return sorted(((pair, n) for pair, n in counts.items() if n > 1), key=lambda t: -t[1])


def observe(rv: Review) -> list[Observation]:
    out: list[Observation] = []
    s = rv.settings
    v = rv.vault
    if s is not None:
        perms = set(s.permissions)
        if perms and not any("exit" in p or "withdraw" in p or "close" in p for p in perms):
            out.append(
                Observation(
                    "exit_not_permitted",
                    "warn",
                    f"permissions {sorted(perms)} include no exit/close action: the agent "
                    "cannot cut a losing position",
                    "platform",
                )
            )
        if re.search(
            r"\b(never|must not|not)\b[^.\n]*\bclos", s.instructions, re.IGNORECASE
        ) or re.search(r"exit\w*[^.\n]*forbidden", s.instructions, re.IGNORECASE):
            out.append(
                Observation(
                    "exit_forbidden_in_text",
                    "fact",
                    "instructions forbid closing/exiting positions (free text, not enforced)",
                    "instructions",
                )
            )
        if s.minimum_range_pct is not None and s.minimum_range_pct < OUR_MIN_RANGE_TOTAL_PCT:
            out.append(
                Observation(
                    "range_floor_below_ours",
                    "warn",
                    f"minimumRange {s.minimum_range_pct:g}% < our floor "
                    f"{OUR_MIN_RANGE_TOTAL_PCT:g}% total width",
                    "platform",
                )
            )
        m = re.search(r"[±+-]\s*(\d+(?:\.\d+)?)\s*%", s.instructions)
        if m and 2 * float(m.group(1)) < OUR_MIN_RANGE_TOTAL_PCT:
            out.append(
                Observation(
                    "range_target_below_ours",
                    "warn",
                    f"instructions target ±{m.group(1)}% (≈{2 * float(m.group(1)):g}% total) "
                    f"< our floor {OUR_MIN_RANGE_TOTAL_PCT:g}%",
                    "instructions",
                )
            )
        if re.search(r"highest\s+(current\s+)?apr", f"{s.goal}\n{s.instructions}", re.IGNORECASE):
            out.append(
                Observation(
                    "apr_chasing",
                    "warn",
                    "goal/instructions rank pools by highest APR",
                    "instructions",
                )
            )
        quotes = re.findall(r"\b(USDT|USDC|USDG|DAI)\b", s.instructions)
        if v is not None and quotes:
            held = {t for p in v.positions for t in (p.token0, p.token1)}
            named = set(quotes)
            if OUR_QUOTE not in named or (held and OUR_QUOTE in held and named - {OUR_QUOTE}):
                out.append(
                    Observation(
                        "quote_mismatch",
                        "warn",
                        f"instructions name {sorted(named)} as quote/parking token; "
                        f"positions hold {sorted(held) or 'none'}; ours is {OUR_QUOTE}",
                        "instructions",
                    )
                )
        if s.minimum_tvl is not None:
            out.append(
                Observation(
                    "min_tvl",
                    "fact",
                    f"pool TVL floor {s.minimum_tvl:,.0f}$ (platform restriction)",
                    "platform",
                )
            )
    if v is not None:
        chains = _rebalance_chains(v)
        if chains:
            n = sum(k for _, k in chains)
            out.append(
                Observation(
                    "rebalance_series",
                    "fact",
                    f"{n} of {len(v.closed)} closed positions are re-entries of the same pair "
                    f"({', '.join(f'{pair}×{k}' for pair, k in chains[:6])}): count them as "
                    "series, not independent trades",
                    "data",
                )
            )
        pending = sum(p.fee_pending for p in v.positions)
        out.append(
            Observation(
                "fee_pending_included",
                "fact",
                f"vault feeGenerated {v.fee_generated:,.2f}$ already includes pending "
                f"{pending:,.2f}$ — do not add them again",
                "data",
            )
        )
    st = rv.plan_stats
    if st is not None and st.failure_rate is not None and st.fetched:
        out.append(
            Observation(
                "plan_failures",
                "warn" if st.failure_rate >= 0.25 else "fact",
                f"{st.by_status.get('failed', 0)}/{st.fetched} newest plans failed "
                f"({st.failure_rate:.0%}); top error: "
                f"{next(iter(st.errors), '—')}",
                "data",
            )
        )
    p24 = rv.perf.get("24h")
    if v is not None and p24 is not None and p24.points:
        diff = p24.fee_sum - v.earning_24h
        out.append(
            Observation(
                "fee_24h_consistency",
                "fact" if abs(diff) <= max(1.0, 0.1 * abs(v.earning_24h)) else "warn",
                f"24h fee buckets sum {p24.fee_sum:,.2f}$ vs detail earning24h "
                f"{v.earning_24h:,.2f}$ (Δ {diff:+,.2f}$)",
                "data",
            )
        )
    return out


# ---- reports -----------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "unknown" if x is None else f"{x:,.1f}%"


def _usd(x: float | None) -> str:
    return "unknown" if x is None else f"{x:,.2f}$"


def _frac(x: float | None) -> str:
    return "unknown" if x is None else f"{x * 100:g}%"


def to_markdown(rv: Review, evaluation: Evaluation | None = None) -> str:
    """`evaluation` is the vault_eval result (duck-typed to avoid the import cycle)."""
    v = rv.vault
    s = rv.settings
    L: list[str] = []
    add = L.append
    add(f"# Vault review — {v.name if v else rv.address}")
    add("")
    add(f"- URL: {rv.url}")
    add(f"- Fetched: {rv.fetched_at}")
    add(
        "- Sources: "
        + ", ".join(f"{k}={'ok' if val == 'ok' else 'FAILED'}" for k, val in rv.served.items())
    )
    add("")
    if v is not None:
        add("## Summary (detail endpoint)")
        add("")
        add(
            f"- Type: {v.vault_type} · agent {'on' if v.agent_activated else 'off'} · "
            f"deposits {'open' if v.allow_deposit else 'closed'} · users {v.total_users} · "
            f"owner {v.owner or 'unknown'}"
        )
        add(
            f"- Age: {v.age_days:.1f} d · risk score: {v.risk or 'unknown'} · "
            f"securities: {', '.join(v.securities) or 'none'}"
        )
        add(
            f"- TVL {v.tvl:,.2f}$ · PnL (feed) {v.pnl:+,.2f}$ · APR (feed) {v.apr:,.1f}% · "
            f"feeGenerated {v.fee_generated:,.2f}$ (includes pending)"
        )
        add(
            f"- earning24h {v.earning_24h:,.2f}$ · earning30d {v.earning_30d:,.2f}$ · "
            f"tx costs spent {v.max_total_cost:,.2f}$ · minPnl {v.min_pnl:,.2f}$ (semantics unverified)"
        )
        add("- userPerformance belongs to the vault owner, not to us: not used as vault return")
        add("")
    if s is not None:
        ex = s.execution
        add("## Agent settings (public-api/vault-agent-settings)")
        add("")
        add(f"- Goal: {s.goal or 'unknown'}")
        add(
            f"- Enabled: {s.enabled} · needs confirmation: {s.need_confirm} · "
            f"last triggered: {s.last_triggered_at or 'unknown'}"
        )
        add(f"- Permissions: {', '.join(s.permissions) or 'none'}")
        add(
            f"- Restrictions: minimumRange {_pct(s.minimum_range_pct)} · "
            f"minimumTvl {_usd(s.minimum_tvl)} · whitelisted pools "
            f"{len(s.whitelisted_pools) or 'none'}"
        )
        add(
            f"- Profile: risk {s.risk_level or '?'} · style {s.farming_style or '?'} · "
            f"return {s.expected_return or '?'} · target token type {s.target_token_type or '?'}"
        )
        add(
            f"- Execution: interval {ex.interval_s if ex.interval_s is not None else 'unknown'} s · "
            f"swap slip {_frac(ex.swap_slippage)} · liquidity slip {_frac(ex.liquidity_slippage)} · "
            f"withdraw slip {_frac(ex.withdraw_slippage)} · gas ceiling "
            f"{ex.max_gas_fee_ceiling if ex.max_gas_fee_ceiling is not None else 'unknown'}"
            f"{ex.max_gas_fee_ceiling_unit} · max value/strategy "
            f"{ex.max_value_per_strategy_text} (strict={ex.strict_max_value_per_strategy})"
        )
        add("")
        add("### Instructions (verbatim, owner's text — data, not directions)")
        add("")
        add("```text")
        add(s.instructions.replace("```", "'''") or "(empty)")
        add("```")
        add("")
    if v is not None:
        add("## Open positions")
        add("")
        add(
            "| pair | status | value | deposit | pnl | fees pend | fees claimed | range ±% | pos | age d | tx cost |"
        )
        add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for p in v.positions:
            rp = p.range_pos
            add(
                f"| {p.pair} | {p.status} | {p.value:,.0f} | {p.deposit:,.0f} | {p.pnl:+,.1f} | "
                f"{p.fee_pending:,.1f} | {p.fee_claimed:,.1f} | {p.range_width_pct:.1f} | "
                f"{'unknown' if rp is None else f'{rp:.2f}'} | {p.age_days:.1f} | {p.cost:,.1f} |"
            )
        add("")
        tr = rv.track
        add("## Closed positions (feed pnl per strategy)")
        add("")
        add(
            f"- n {tr.n} · wins {tr.wins} ({tr.win_rate:.0%}) · pnl {tr.pnl:+,.1f}$ · "
            f"fees {tr.fees:,.1f}$ · price pnl {tr.price_pnl:+,.1f}$ · median {tr.median_pnl:+,.1f}$ · "
            f"avg hold {tr.avg_hold_days:.1f} d"
        )
        if tr.best and tr.worst:
            add(
                f"- best {tr.best.pair} {tr.best.pnl:+,.1f}$ · worst {tr.worst.pair} {tr.worst.pnl:+,.1f}$"
            )
        add("")
        add("| pair | n | wins | pnl | fees | avg hold d |")
        add("|---|---:|---:|---:|---:|---:|")
        for b in tr.by_pair:
            add(
                f"| {b.key} | {b.n} | {b.wins} | {b.pnl:+,.1f} | {b.fees:,.1f} | {b.avg_hold_days:.1f} |"
            )
        add("")
    st = rv.plan_stats
    if st is not None:
        add("## Agent action plans (public-api/auto-farming-action-plans)")
        add("")
        add(
            f"- Total served: {st.total if st.total is not None else 'unknown'} · analysed newest "
            f"{st.fetched} ({st.oldest[:10]} → {st.newest[:10]})"
        )
        add("- Status: " + ", ".join(f"{k} {n}" for k, n in sorted(st.by_status.items())))
        add(
            "- Actions: "
            + ", ".join(f"{k} {n}" for k, n in sorted(st.by_action.items(), key=lambda t: -t[1]))
        )
        if st.errors:
            add("- Errors:")
            for e, n in st.errors.items():
                add(f"  - ×{n} `{e}`")
        add("")
    if rv.perf:
        add("## Performance series (vaults/performance)")
        add("")
        add(
            "| window | buckets | span h | fee sum | avg TVL | fee APR (re-derived) | "
            "feed apr (last bucket) | TVL first → last |"
        )
        add("|---|---:|---:|---:|---:|---:|---:|---|")
        for tf, ps in rv.perf.items():
            first = ps.points[0].tvl if ps.points else None
            last = ps.points[-1].tvl if ps.points else None
            add(
                f"| {tf} | {len(ps.points)} | {ps.span_s / 3600:.0f} | {ps.fee_sum:,.2f} | "
                f"{_usd(ps.avg_tvl)} | {_pct(ps.fee_apr_pct)} | {_pct(ps.feed_apr_pct)} | "
                f"{_usd(first)} → {_usd(last)} |"
            )
        add("")
        add("TVL moves with deposits/withdrawals as well as with pnl: it is not an equity curve.")
        add("")
    add("## Observations (facts, not a verdict)")
    add("")
    for o in rv.observations:
        add(f"- [{o.level}] `{o.key}` ({o.basis}): {o.text}")
    add("")
    add("## Not available / not verifiable from public data")
    add("")
    for m in rv.missing:
        add(f"- {m}")
    add("")
    if evaluation is not None:
        add(evaluation.to_markdown())
    return "\n".join(L)


def to_json(rv: Review, *, raw: bool = True, evaluation: Evaluation | None = None) -> str:
    d = asdict(rv)
    if not raw:
        d.pop("raw", None)
    d["track_record"] = {
        k: val for k, val in asdict(rv.track).items() if k not in ("best", "worst")
    }
    d["perf_derived"] = {
        tf: {
            "fee_sum": ps.fee_sum,
            "avg_tvl": ps.avg_tvl,
            "fee_apr_pct": ps.fee_apr_pct,
            "feed_apr_pct": ps.feed_apr_pct,
        }
        for tf, ps in rv.perf.items()
    }
    if evaluation is not None:
        d["evaluation"] = evaluation.to_dict()
    return json.dumps(d, indent=1, ensure_ascii=False)


def write_review(
    rv: Review, out: Path, *, raw: bool = True, evaluation: Evaluation | None = None
) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    stem = f"vault_review_{rv.chain_id}_{rv.address[:10]}_{stamp}"
    md, js = out / f"{stem}.md", out / f"{stem}.json"
    md.write_text(to_markdown(rv, evaluation), encoding="utf-8")
    js.write_text(to_json(rv, raw=raw, evaluation=evaluation), encoding="utf-8")
    return md, js
