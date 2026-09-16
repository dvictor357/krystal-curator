"""vault_eval: performance, risk-fit checks by basis, evidence floor, rule-based verdict."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from krystal_curator import vault_eval as ve
from krystal_curator import vault_review as vr
from krystal_curator.vaults import _parse_vault, parse_strategy

FIX = Path(__file__).parent / "fixtures" / "vault_review"


def _review(*, settings: dict | None = ..., perf: bool = True, detail_patch=None) -> vr.Review:
    """A Review built straight from the fixtures, no network."""
    detail = json.loads((FIX / "detail.json").read_text())
    if detail_patch:
        detail_patch(detail)
    v = _parse_vault(detail, owned=False)
    for s in detail["strategies"]:
        p = parse_strategy(s, v.name)
        (v.closed if p.status == "CLOSED" else v.positions).append(p)
    rv = vr.Review(fetched_at="t", chain_id=4663, address=v.address, url=v.url, vault=v)
    rv.served["detail"] = "ok"
    if settings is ...:
        settings = json.loads((FIX / "settings.json").read_text())
    if settings is not None:
        rv.settings = vr.parse_settings(settings)
        rv.served["settings"] = "ok"
    else:
        rv.served["settings"] = "settings: HTTP 502"
        rv.missing.append("agent settings")
    plans = json.loads((FIX / "plans.json").read_text())
    rv.plans = [vr.parse_plan(r) for r in plans["data"]]
    rv.plan_stats = vr.plan_stats(rv.plans, plans["pagination"]["total"])
    if perf:
        for tf in ("24h", "30d"):
            rv.perf[tf] = vr.parse_perf(tf, json.loads((FIX / f"perf_{tf}.json").read_text()))
    return rv


def _good_settings() -> dict:
    """What a vault that fits our goals would serve."""
    s = json.loads((FIX / "settings.json").read_text())
    cfg = s["autoFarmingConfig"]
    cfg["permissions"] = ["swap_and_mint", "adjust_range", "harvest", "exit"]
    cfg["restrictions"] = {"minimumRange": 20, "minimumTvl": 250_000, "whitelistedPools": []}
    cfg["executionConfig"]["interval"] = 3_600_000
    cfg["executionConfig"]["maxValuePerStrategy"] = 0.1
    cfg["instructions"] = (
        "Keep every position paired with USDG. Rebalance to ±12% around spot when out of "
        "range. Never add liquidity to a position that is not profitable. Park idle funds "
        "in USDG."
    )
    s["goal"] = "Grow NAV in USDG with sustainable fees."
    return s


def _many_series(detail: dict) -> None:
    """Pad the closed list so the evidence floor (10 series) is met, all USDG-quoted."""
    base = next(s for s in detail["strategies"] if s["status"] == "CLOSED")
    for i in range(12):
        s = copy.deepcopy(base)
        s["strategyId"] = 1_000 + i
        s["tokens"] = [{"symbol": "USDG"}, {"symbol": f"T{i}"}]
        s["pnl"], s["feeGenerated"], s["maxTotalCost"] = 20.0, 30.0, 1.0
        detail["strategies"].append(s)
    for s in detail["strategies"]:
        if "USDG" not in [t["symbol"] for t in s["tokens"]]:
            s["tokens"] = [{"symbol": "USDG"}, {"symbol": "X"}]
    # two open positions, within our limit
    detail["strategies"] = [
        s for s in detail["strategies"] if s["status"] == "CLOSED" or s["strategyId"] != 98412458
    ]


# ---- performance -----------------------------------------------------------------------


def test_performance_counts_series_not_strategy_ids_and_nets_tx_costs():
    pf = ve.performance(_review())
    assert pf.closed_positions == 6 and pf.closed_series == 4  # MICRODUCK×2, ETH/PAR×2
    assert pf.closed_price_pnl == pytest.approx(pf.closed_pnl - pf.closed_fees)
    assert pf.closed_pnl_after_tx == pytest.approx(pf.closed_pnl - pf.closed_tx_costs)
    assert pf.closed_tx_costs > 0
    assert pf.open_positions == 3 and 0 < pf.largest_position_share < 1
    assert set(pf.fee_apr_rederived) == {"24h", "30d"} and pf.fee_stability is not None
    assert "whether the feed's pnl already nets transaction costs" in pf.unknown


def test_performance_ignores_deposits_and_withdrawals():
    """The owner's deposit / withdrawal totals are not profit or loss."""
    a = ve.performance(_review())
    b = ve.performance(
        _review(
            detail_patch=lambda d: d["userPerformance"].update(
                totalDepositValue=1e6, totalWithdrawValue=0
            )
        )
    )
    assert a == b


def test_performance_without_series_marks_unknown():
    pf = ve.performance(_review(perf=False))
    assert pf.fee_stability is None and "fee APR by window" in pf.unknown


# ---- checks ---------------------------------------------------------------------------


def test_checks_classify_by_basis_on_the_source_vault():
    cks = {c.key: c for c in ve.checks(_review())}
    assert cks["exit_permitted"].result == "fail" and cks["exit_permitted"].basis == "platform"
    assert cks["min_range_platform"].result == "fail" and "5%" in cks["min_range_platform"].evidence
    assert cks["min_pool_tvl"].result == "fail"
    assert cks["cooldown"].result == "fail" and "1800" in cks["cooldown"].evidence
    assert cks["position_budget"].result == "pass"  # 15 % of a 1.6 k$ vault < 300 $
    assert cks["range_target_text"].result == "fail" and "10%" in cks["range_target_text"].evidence
    assert cks["apr_chasing"].result == "fail" and cks["apr_chasing"].basis == "instructions"
    assert cks["no_adding_to_losers"].result == "pass"
    assert cks["quote_in_text"].result == "fail" and "USDT" in cks["quote_in_text"].evidence
    assert (
        cks["quote_only_positions"].result == "fail"
        and "ETH/PAR" in cks["quote_only_positions"].evidence
    )
    assert cks["chain_protocol"].result == "pass"
    assert cks["max_positions"].result == "fail"
    assert cks["drawdown"].result == "unknown" and cks["drawdown"].basis == "data"


def test_checks_without_settings_are_unknown_not_fail():
    cks = ve.checks(_review(settings=None))
    assert all(c.result == "unknown" for c in cks if c.basis in ("platform", "instructions"))
    assert any(c.basis == "data" and c.result != "unknown" for c in cks)  # positions still speak


def test_min_pool_tvl_exception_is_a_fail_with_a_note():
    s = json.loads((FIX / "settings.json").read_text())
    s["autoFarmingConfig"]["restrictions"]["minimumTvl"] = 160_000
    c = {c.key: c for c in ve.checks(_review(settings=s))}["min_pool_tvl"]
    assert c.result == "fail" and "exception" in c.evidence


@pytest.mark.parametrize(
    "text,width",
    [
        ("adjust range to approximately 10% total width (±5% around current market price)", 10),
        ("rebalance to ±12% around spot", 24),
        ("use a 30% total range", 30),
        ("no numbers here", None),
    ],
)
def test_range_target_from_text(text, width):
    assert ve._range_target_from_text(text) == width


def test_limits_are_applied_not_hardcoded():
    lim = replace(ve.DEFAULT_LIMITS, min_range_total_pct=4.0, cooldown_s=600.0, min_pool_tvl=500.0)
    cks = {c.key: c for c in ve.checks(_review(), lim)}
    assert cks["min_range_platform"].result == "pass"
    assert cks["cooldown"].result == "pass"
    assert cks["min_pool_tvl"].result == "pass"


# ---- verdict --------------------------------------------------------------------------


def test_source_vault_is_avoid_despite_its_apr():
    ev = ve.evaluate(_review())
    assert ev.verdict == "avoid"
    assert any(r.startswith("exit_permitted") for r in ev.reasons)
    assert ev.performance.fees_cover_price_moves is not None  # performance still reported


def test_missing_settings_is_insufficient_data():
    ev = ve.evaluate(_review(settings=None))
    assert ev.verdict == "insufficient_data" and "no agent settings" in ev.reasons


def test_young_vault_with_clean_platform_is_insufficient_data():
    ev = ve.evaluate(_review(settings=_good_settings()))
    assert ev.verdict == "insufficient_data"
    assert any("closed series" in r for r in ev.reasons)


def test_clean_vault_with_paying_fee_record_is_worth_testing():
    ev = ve.evaluate(_review(settings=_good_settings(), detail_patch=_many_series))
    assert ev.evidence.enough, ev.evidence.why_not
    assert not [c for c in ev.checks if c.basis == "platform" and c.result == "fail"]
    assert ev.verdict == "worth_testing", ev.reasons
    assert ev.performance.fees_cover_price_moves is True


def test_clean_vault_whose_fees_do_not_pay_is_watch():
    def patch(d):
        _many_series(d)
        for s in d["strategies"]:
            if s["status"] == "CLOSED":
                s["pnl"] = -50.0  # price losses eat every fee

    ev = ve.evaluate(_review(settings=_good_settings(), detail_patch=patch))
    assert ev.verdict == "watch"
    assert any("does not pay" in r for r in ev.reasons)


def test_verdict_is_one_of_the_enum():
    for rv in (_review(), _review(settings=None), _review(settings=_good_settings())):
        assert ve.evaluate(rv).verdict in ve.VERDICTS


# ---- output ---------------------------------------------------------------------------


def test_evaluation_renders_into_the_review_report(tmp_path):
    rv = _review()
    ev = ve.evaluate(rv)
    md, js = vr.write_review(rv, tmp_path, evaluation=ev)
    text = md.read_text()
    assert "## Evaluation — verdict: **avoid**" in text
    assert "| exit_permitted | fail | platform |" in text
    data = json.loads(js.read_text())
    assert data["evaluation"]["verdict"] == "avoid"
    assert data["evaluation"]["limits"]["protocols"] == ["uniswapv3", "uniswapv4"]
    assert data["evaluation"]["performance"]["closed_series"] == 4
