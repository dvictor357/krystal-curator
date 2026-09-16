"""Evaluate a reviewed vault against our own goals: three separate answers, then a verdict.

1. Observed performance — what the closed and open positions actually did, with the
   costs that are known, and how stable the fee income was across windows.
2. Risk fit — one check per rule of ours. Each check says pass / fail / unknown and on
   what basis: `platform` (a control Krystal enforces: permissions, restrictions,
   execution settings), `instructions` (the owner's free text, which only the agent
   reads), or `data` (what the positions show). A fail on a platform control cannot be
   fixed by rewriting the prompt.
3. Evidence — how much of this rests on data: age, closed series, plan coverage,
   sources that failed, metrics the public API does not serve.

The verdict is a rule, not a score: a platform-level fail is `avoid` (for copying as
is) no matter how high the APR; thin evidence is `insufficient_data`; instruction-level
fails only are `worth_testing` when the fee record pays for the price moves, else
`watch`. No LLM is consulted here.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from .vault_review import Review

VERDICTS = ("worth_testing", "watch", "avoid", "insufficient_data")


@dataclass(slots=True, frozen=True)
class Limits:
    """Our goals, as numbers. The adaptation stage enforces the same limits."""

    chain_id: int = 4663
    protocols: frozenset[str] = frozenset({"uniswapv3", "uniswapv4"})
    quote: str = "USDG"
    max_positions: int = 2
    second_position_budget: float = 300.0  # USD, from idle funds
    min_range_total_pct: float = 20.0
    min_pool_tvl: float = 250_000.0  # default entry
    min_pool_tvl_exception: float = 150_000.0  # only as a documented, user-chosen exception
    cooldown_s: float = 3600.0  # between major actions
    loss_limit_usd: float = 200.0  # combined, a trigger — not a guaranteed max loss
    min_age_days: float = 14.0  # evidence floor
    min_closed_series: int = 10  # evidence floor


DEFAULT_LIMITS = Limits()

EXIT_WORDS = ("exit", "close", "withdraw", "remove")


@dataclass(slots=True)
class Check:
    key: str
    result: str  # pass / fail / unknown
    basis: str  # platform / instructions / data
    rule: str
    evidence: str


@dataclass(slots=True)
class Performance:
    closed_positions: int = 0
    closed_series: int = 0  # distinct pairs among closed positions
    closed_pnl: float = 0.0
    closed_fees: float = 0.0
    closed_price_pnl: float = 0.0  # pnl − fees
    closed_tx_costs: float = 0.0
    closed_pnl_after_tx: float = 0.0  # a lower bound if the feed's pnl already nets costs
    series_win_rate: float | None = None  # per pair series, not per strategy id
    fees_cover_price_moves: bool | None = None
    open_positions: int = 0
    open_value: float = 0.0
    open_pnl: float = 0.0
    open_fee_pending: float = 0.0
    open_tx_costs: float = 0.0
    largest_position_share: float | None = None  # of TVL
    fee_apr_rederived: dict[str, float | None] = field(default_factory=dict)
    fee_apr_feed: dict[str, float | None] = field(default_factory=dict)
    fee_stability: float | None = None  # max / min of the re-derived fee APRs
    unknown: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Evidence:
    age_days: float | None = None
    closed_positions: int = 0
    closed_series: int = 0
    plans_analysed: int = 0
    plans_total: int | None = None
    sources_failed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    enough: bool = False
    why_not: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Evaluation:
    verdict: str
    reasons: list[str]
    performance: Performance
    checks: list[Check]
    evidence: Evidence
    limits: Limits

    def to_dict(self) -> dict:
        d = asdict(self)
        d["limits"]["protocols"] = sorted(self.limits.protocols)
        return d

    def to_markdown(self) -> str:
        return evaluation_markdown(self)


# ---- performance ---------------------------------------------------------------------


def performance(rv: Review) -> Performance:
    pf = Performance()
    v = rv.vault
    if v is None:
        pf.unknown.append("no vault detail")
        return pf
    closed = v.closed
    pf.closed_positions = len(closed)
    by_pair: dict[str, list] = {}
    for p in closed:
        by_pair.setdefault(p.pair, []).append(p)
    pf.closed_series = len(by_pair)
    pf.closed_pnl = sum(p.pnl for p in closed)
    pf.closed_fees = sum(p.fees_total for p in closed)
    pf.closed_price_pnl = pf.closed_pnl - pf.closed_fees
    pf.closed_tx_costs = sum(p.cost for p in closed)
    pf.closed_pnl_after_tx = pf.closed_pnl - pf.closed_tx_costs
    if by_pair:
        wins = sum(1 for ps in by_pair.values() if sum(p.pnl for p in ps) > 0)
        pf.series_win_rate = wins / len(by_pair)
        pf.fees_cover_price_moves = pf.closed_fees > -pf.closed_price_pnl
    pf.open_positions = len(v.positions)
    pf.open_value = sum(p.value for p in v.positions)
    pf.open_pnl = sum(p.pnl for p in v.positions)
    pf.open_fee_pending = sum(p.fee_pending for p in v.positions)
    pf.open_tx_costs = sum(p.cost for p in v.positions)
    if v.positions and v.tvl > 0:
        pf.largest_position_share = max(p.value for p in v.positions) / v.tvl
    for tf, ps in rv.perf.items():
        pf.fee_apr_rederived[tf] = ps.fee_apr_pct
        pf.fee_apr_feed[tf] = ps.feed_apr_pct
    known = [x for x in pf.fee_apr_rederived.values() if x is not None and x > 0]
    if len(known) >= 2:
        pf.fee_stability = max(known) / min(known)
    else:
        pf.unknown.append("fee stability (fewer than two windows served)")
    if not rv.perf:
        pf.unknown.append("fee APR by window")
    pf.unknown.append("costs other than transaction costs")
    pf.unknown.append("whether the feed's pnl already nets transaction costs")
    return pf


# ---- risk fit ----------------------------------------------------------------------------


def _range_target_from_text(text: str) -> float | None:
    """`±5%` → 10 (total width); `10% total width` → 10; None when the text says nothing."""
    m = re.search(r"[±+-]\s*(\d+(?:\.\d+)?)\s*%", text)
    if m:
        return 2 * float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*total\s*(?:width|range)", text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def checks(rv: Review, lim: Limits = DEFAULT_LIMITS) -> list[Check]:
    out: list[Check] = []
    s = rv.settings
    v = rv.vault
    unknown_settings = "agent settings not served"

    # -- platform controls ---------------------------------------------------------------
    if s is None:
        out.append(
            Check(
                "exit_permitted",
                "unknown",
                "platform",
                "agent may exit a position",
                unknown_settings,
            )
        )
        out.append(
            Check(
                "min_range_platform",
                "unknown",
                "platform",
                f"minimumRange ≥ {lim.min_range_total_pct:g}%",
                unknown_settings,
            )
        )
        out.append(
            Check(
                "min_pool_tvl",
                "unknown",
                "platform",
                f"minimumTvl ≥ {lim.min_pool_tvl:,.0f}$",
                unknown_settings,
            )
        )
        out.append(
            Check(
                "position_budget",
                "unknown",
                "platform",
                f"max value per strategy ≤ {lim.second_position_budget:,.0f}$",
                unknown_settings,
            )
        )
        out.append(
            Check(
                "cooldown",
                "unknown",
                "platform",
                f"interval ≥ {lim.cooldown_s:g} s",
                unknown_settings,
            )
        )
    else:
        perms = s.permissions
        has_exit = any(any(w in p for w in EXIT_WORDS) for p in perms)
        out.append(
            Check(
                "exit_permitted",
                "pass" if has_exit else ("fail" if perms else "unknown"),
                "platform",
                "agent may exit a position",
                f"permissions {perms or 'none served'}",
            )
        )
        mr = s.minimum_range_pct
        out.append(
            Check(
                "min_range_platform",
                "unknown" if mr is None else ("pass" if mr >= lim.min_range_total_pct else "fail"),
                "platform",
                f"minimumRange ≥ {lim.min_range_total_pct:g}% total width",
                "not served" if mr is None else f"minimumRange {mr:g}%",
            )
        )
        mt = s.minimum_tvl
        if mt is None:
            res, ev = "unknown", "not served"
        elif mt >= lim.min_pool_tvl:
            res, ev = "pass", f"minimumTvl {mt:,.0f}$"
        elif mt >= lim.min_pool_tvl_exception:
            res, ev = (
                "fail",
                f"minimumTvl {mt:,.0f}$ — passes only under the {lim.min_pool_tvl_exception:,.0f}$ exception",
            )
        else:
            res, ev = "fail", f"minimumTvl {mt:,.0f}$"
        out.append(
            Check(
                "min_pool_tvl",
                res,
                "platform",
                f"minimumTvl ≥ {lim.min_pool_tvl:,.0f}$ (exception {lim.min_pool_tvl_exception:,.0f}$)",
                ev,
            )
        )
        ex = s.execution
        mv = ex.max_value_per_strategy
        if mv is None or v is None:
            res, ev = "unknown", "not served"
        else:
            cap = mv * v.tvl if ex.max_value_per_strategy_unit == "%" else mv
            res = "pass" if cap <= lim.second_position_budget else "fail"
            ev = f"{ex.max_value_per_strategy_text} = {cap:,.0f}$ on TVL {v.tvl:,.0f}$"
        out.append(
            Check(
                "position_budget",
                res,
                "platform",
                f"max value per strategy ≤ {lim.second_position_budget:,.0f}$",
                ev,
            )
        )
        it = ex.interval_s
        out.append(
            Check(
                "cooldown",
                "unknown" if it is None else ("pass" if it >= lim.cooldown_s else "fail"),
                "platform",
                f"agent interval ≥ {lim.cooldown_s:g} s",
                "not served" if it is None else f"interval {it:g} s",
            )
        )

    # -- instructions (free text: the agent reads it, nothing enforces it) --------------
    if s is None:
        out.append(
            Check(
                "range_target_text",
                "unknown",
                "instructions",
                f"rebalance target ≥ {lim.min_range_total_pct:g}% total",
                unknown_settings,
            )
        )
        out.append(
            Check(
                "apr_chasing",
                "unknown",
                "instructions",
                "selection not ranked by highest APR",
                unknown_settings,
            )
        )
        out.append(
            Check(
                "no_adding_to_losers",
                "unknown",
                "instructions",
                "no capital added to a losing position",
                unknown_settings,
            )
        )
        out.append(
            Check(
                "quote_in_text",
                "unknown",
                "instructions",
                f"parking / quote token is {lim.quote}",
                unknown_settings,
            )
        )
    else:
        text = f"{s.goal}\n{s.instructions}"
        tw = _range_target_from_text(s.instructions)
        out.append(
            Check(
                "range_target_text",
                "unknown" if tw is None else ("pass" if tw >= lim.min_range_total_pct else "fail"),
                "instructions",
                f"rebalance target ≥ {lim.min_range_total_pct:g}% total width",
                "no range target in text" if tw is None else f"text targets {tw:g}% total",
            )
        )
        apr = re.search(r"highest\s+(current\s+)?apr", text, re.IGNORECASE)
        out.append(
            Check(
                "apr_chasing",
                "fail" if apr else "pass",
                "instructions",
                "selection not ranked by highest APR alone",
                f"text: {apr.group(0)!r}" if apr else "no 'highest APR' ranking in text",
            )
        )
        loser_guard = re.search(
            r"(must not|never|forbidden)[^.\n]*\b(increas|add|allocat)\w*[^.\n]*\b(not profitable|unprofitable|los)",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"(not profitable|unprofitable|los\w+)[^.\n]*\b(must not|never|forbidden)[^.\n]*\b(increas|add|allocat)",
            text,
            re.IGNORECASE,
        )
        out.append(
            Check(
                "no_adding_to_losers",
                "pass" if loser_guard else "unknown",
                "instructions",
                "no capital added to a losing position",
                f"text: {loser_guard.group(0)[:80]!r}" if loser_guard else "no such rule in text",
            )
        )
        named = set(re.findall(r"\b(USDT|USDC|USDG|DAI|USDC\.e)\b", s.instructions))
        if not named:
            res, ev = "unknown", "no stable named in text"
        elif named == {lim.quote}:
            res, ev = "pass", f"text names {sorted(named)}"
        else:
            res, ev = "fail", f"text names {sorted(named)}"
        out.append(
            Check("quote_in_text", res, "instructions", f"parking / quote token is {lim.quote}", ev)
        )

    # -- data (what the positions show) --------------------------------------------------
    if v is None:
        return out
    all_pos = v.positions + v.closed
    off_quote = sorted({p.pair for p in all_pos if lim.quote not in (p.token0, p.token1)})
    out.append(
        Check(
            "quote_only_positions",
            "pass" if not off_quote else "fail",
            "data",
            f"every position is paired with {lim.quote}",
            f"{len(all_pos)} positions, off-quote: {off_quote[:8] or 'none'}",
        )
    )
    protos = Counter(p.protocol for p in all_pos)
    bad = sorted(k for k in protos if k not in lim.protocols)
    out.append(
        Check(
            "chain_protocol",
            "pass" if v.chain_id == lim.chain_id and not bad else "fail",
            "data",
            f"chain {lim.chain_id}, protocols {sorted(lim.protocols)}",
            f"chain {v.chain_id}, protocols {dict(protos)}",
        )
    )
    out.append(
        Check(
            "max_positions",
            "pass" if len(v.positions) <= lim.max_positions else "fail",
            "data",
            f"≤ {lim.max_positions} open positions",
            f"{len(v.positions)} open",
        )
    )
    nav = any(ps.share_price_known for ps in rv.perf.values())
    out.append(
        Check(
            "drawdown",
            "unknown",
            "data",
            "max drawdown from NAV per share",
            "sharePriceUsd served" if nav else "sharePriceUsd is 0: not derivable from TVL",
        )
    )
    return out


# ---- evidence --------------------------------------------------------------------------------


def evidence(rv: Review, pf: Performance, lim: Limits = DEFAULT_LIMITS) -> Evidence:
    ev = Evidence(
        age_days=rv.vault.age_days if rv.vault else None,
        closed_positions=pf.closed_positions,
        closed_series=pf.closed_series,
        plans_analysed=rv.plan_stats.fetched if rv.plan_stats else 0,
        plans_total=rv.plan_stats.total if rv.plan_stats else None,
        sources_failed=[k for k, val in rv.served.items() if val != "ok"],
        missing=list(rv.missing),
    )
    if rv.vault is None:
        ev.why_not.append("no vault detail")
    if rv.settings is None:
        ev.why_not.append("no agent settings")
    if ev.age_days is not None and ev.age_days < lim.min_age_days:
        ev.why_not.append(f"age {ev.age_days:.1f} d < {lim.min_age_days:g} d")
    if ev.closed_series < lim.min_closed_series:
        ev.why_not.append(f"{ev.closed_series} closed series < {lim.min_closed_series}")
    if not rv.perf:
        ev.why_not.append("no performance series")
    ev.enough = not ev.why_not
    return ev


# ---- verdict --------------------------------------------------------------------------------


def evaluate(rv: Review, lim: Limits = DEFAULT_LIMITS) -> Evaluation:
    pf = performance(rv)
    cks = checks(rv, lim)
    evd = evidence(rv, pf, lim)
    reasons: list[str] = []

    platform_fails = [c for c in cks if c.basis == "platform" and c.result == "fail"]
    text_fails = [c for c in cks if c.basis == "instructions" and c.result == "fail"]
    data_fails = [c for c in cks if c.basis == "data" and c.result == "fail"]

    if rv.vault is None or rv.settings is None:
        verdict = "insufficient_data"
        reasons += evd.why_not
    elif platform_fails:
        verdict = "avoid"
        reasons += [
            f"{c.key}: {c.evidence} (platform control, not fixable in text)" for c in platform_fails
        ]
        if not evd.enough:
            reasons += [f"also thin evidence: {w}" for w in evd.why_not]
    elif not evd.enough:
        verdict = "insufficient_data"
        reasons += evd.why_not
    else:
        adaptable = text_fails + data_fails
        pays = pf.fees_cover_price_moves is True and pf.closed_pnl_after_tx > 0
        if pays:
            verdict = "worth_testing"
            reasons.append(
                f"closed fees {pf.closed_fees:,.0f}$ cover price moves {pf.closed_price_pnl:+,.0f}$; "
                f"pnl after tx costs {pf.closed_pnl_after_tx:+,.0f}$"
            )
            if adaptable:
                reasons.append("adaptation required: " + ", ".join(c.key for c in adaptable))
        else:
            verdict = "watch"
            reasons.append(
                f"fee record does not pay for price moves (fees {pf.closed_fees:,.0f}$, "
                f"price pnl {pf.closed_price_pnl:+,.0f}$, after tx {pf.closed_pnl_after_tx:+,.0f}$)"
            )
            reasons += [f"{c.key}: {c.evidence}" for c in adaptable]
    if pf.fee_stability is not None and pf.fee_stability > 3:
        reasons.append(f"fee APR varies {pf.fee_stability:.1f}× across windows: income is bursty")
    return Evaluation(verdict, reasons, pf, cks, evd, lim)


# ---- markdown --------------------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "unknown" if x is None else f"{x:,.1f}%"


def evaluation_markdown(ev: Evaluation) -> str:
    pf, evd = ev.performance, ev.evidence
    L: list[str] = []
    add = L.append
    add(f"## Evaluation — verdict: **{ev.verdict}**")
    add("")
    for r in ev.reasons:
        add(f"- {r}")
    add("")
    add("### Observed performance")
    add("")
    add(
        f"- Closed: {pf.closed_positions} positions in {pf.closed_series} pair series · "
        f"pnl {pf.closed_pnl:+,.1f}$ · fees {pf.closed_fees:,.1f}$ · price pnl "
        f"{pf.closed_price_pnl:+,.1f}$ · tx costs {pf.closed_tx_costs:,.1f}$ · "
        f"pnl after tx {pf.closed_pnl_after_tx:+,.1f}$"
    )
    add(
        f"- Series win rate {('unknown' if pf.series_win_rate is None else f'{pf.series_win_rate:.0%}')} · "
        f"fees cover price moves: {pf.fees_cover_price_moves}"
    )
    add(
        f"- Open: {pf.open_positions} positions · value {pf.open_value:,.0f}$ · pnl {pf.open_pnl:+,.1f}$ · "
        f"pending fees {pf.open_fee_pending:,.1f}$ · tx costs {pf.open_tx_costs:,.1f}$ · "
        f"largest share of TVL {('unknown' if pf.largest_position_share is None else f'{pf.largest_position_share:.0%}')}"
    )
    if pf.fee_apr_rederived:
        add(
            "- Fee APR by window (re-derived / feed): "
            + " · ".join(
                f"{tf} {_pct(pf.fee_apr_rederived[tf])} / {_pct(pf.fee_apr_feed.get(tf))}"
                for tf in pf.fee_apr_rederived
            )
            + f" · stability {('unknown' if pf.fee_stability is None else f'{pf.fee_stability:.1f}×')}"
        )
    for u in pf.unknown:
        add(f"- unknown: {u}")
    add("")
    add("### Risk fit")
    add("")
    add("| check | result | basis | rule | evidence |")
    add("|---|---|---|---|---|")
    for c in ev.checks:
        add(f"| {c.key} | {c.result} | {c.basis} | {c.rule} | {c.evidence} |")
    add("")
    add("### Evidence")
    add("")
    add(
        f"- Age {('unknown' if evd.age_days is None else f'{evd.age_days:.1f} d')} · closed series "
        f"{evd.closed_series} ({evd.closed_positions} positions) · plans analysed "
        f"{evd.plans_analysed} of {evd.plans_total if evd.plans_total is not None else 'unknown'}"
    )
    add(f"- Sources failed: {', '.join(evd.sources_failed) or 'none'}")
    add(
        f"- Enough for a verdict beyond insufficient_data: {evd.enough}"
        + (f" — {'; '.join(evd.why_not)}" if evd.why_not else "")
    )
    add("")
    lim = ev.limits
    add(
        f"Limits applied: chain {lim.chain_id} · {sorted(lim.protocols)} · quote {lim.quote} · "
        f"≤ {lim.max_positions} positions · second position ≤ {lim.second_position_budget:,.0f}$ · "
        f"range ≥ {lim.min_range_total_pct:g}% · pool TVL ≥ {lim.min_pool_tvl:,.0f}$ "
        f"(exception {lim.min_pool_tvl_exception:,.0f}$) · cooldown ≥ {lim.cooldown_s:g} s · "
        f"combined loss trigger {lim.loss_limit_usd:,.0f}$ (a trigger, not a floor on actual loss)."
    )
    add("")
    return "\n".join(L)
