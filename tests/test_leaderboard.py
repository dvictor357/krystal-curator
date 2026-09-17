"""vault-leaderboard: the public vault list ranked by owner and by copy candidacy."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from krystal_curator import leaderboard, net
from krystal_curator.cli import main
from krystal_curator.vault_eval import DEFAULT_LIMITS
from krystal_curator.vaults import Vault, fetch_public_vaults

PAGES = json.loads((Path(__file__).parent / "fixtures" / "vault_list.json").read_text())


@pytest.fixture
def offline(monkeypatch):
    calls: list[dict] = []

    def fake_get(url, *, params=None, **kw):
        calls.append(dict(params or {}))
        assert url.endswith("/all/v1/vaults")
        body = PAGES[int(params["page"]) - 1]
        return httpx.Response(200, json=body, request=httpx.Request("GET", url, params=params))

    monkeypatch.setattr(net, "get", fake_get)
    return calls


def _vault(**kw) -> Vault:
    base = {
        "chain_id": 4663,
        "address": "0xv",
        "name": "v",
        "vault_type": "autofarm",
        "owned": False,
        "tvl": 2_000.0,
        "pnl": 200.0,
        "apr": 100.0,
        "fee_generated": 400.0,
        "earning_24h": 5.0,
        "earning_30d": 150.0,
        "risk": "HIGH",
        "age_days": 30.0,
        "my_value": 2_000.0,
        "my_deposit": 4_000.0,
        "my_withdrawn": 2_200.0,
        "owner": "0xowner",
        "agent_activated": True,
        "max_total_cost": 40.0,
    }
    return Vault(**{**base, **kw})


# ---- feed ------------------------------------------------------------------------------


def test_fetch_public_vaults_walks_every_page(offline):
    vaults = fetch_public_vaults(4663)
    assert len(vaults) == 6
    assert [c["page"] for c in offline] == [1, 2]
    assert all(c["chainIds"] == 4663 and c["isAutoFarmVault"] == "true" for c in offline)
    v = next(v for v in vaults if v.name == "Naabu2")
    assert v.owner.startswith("0xdb0358") and v.copy_count == 13 and v.agent_activated
    assert abs(v.fee_apr - 2_820) < 5  # fraction on the feed, percent here
    assert abs(v.my_deposit - 57_064.16) < 0.01  # vault-wide lifetime deposits


# ---- vault rank ----------------------------------------------------------------------


def test_roi_is_on_lifetime_deposits_and_annualised():
    r = leaderboard.rank_vault(_vault())
    assert abs(r.deposited - 4_000) < 1e-9
    assert abs(r.roi_pct - 5.0) < 1e-9  # 200 / 4000
    assert abs(r.roi_ann_pct - 5.0 * 365 / 30) < 1e-9
    assert abs(r.yield_30d_pct - 7.5) < 1e-9  # 150 / 2000
    assert abs(r.cost_share - 0.1) < 1e-9
    assert r.candidate


def test_deposits_fall_back_to_tvl_when_feed_serves_none():
    r = leaderboard.rank_vault(_vault(my_deposit=0.0))
    assert abs(r.deposited - 2_000) < 1e-9 and abs(r.roi_pct - 10.0) < 1e-9


def test_unknown_age_and_tvl_do_not_divide_by_zero():
    r = leaderboard.rank_vault(_vault(age_days=0.0, tvl=0.0, my_deposit=0.0, fee_generated=0.0))
    assert r.roi_ann_pct is None and r.yield_30d_pct is None and r.cost_share is None
    assert abs(r.roi_pct) < 1e-9


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"age_days": 3.0}, "age 3d < 14d"),
        ({"tvl": 100.0}, "tvl 100 < 500"),
        ({"pnl": -5.0}, "pnl -5"),
        ({"fee_generated": 0.0}, "no fees"),
        ({"max_total_cost": 300.0}, "tx costs 75% of fees"),
        ({"agent_activated": False}, "no agent (nothing to copy)"),
    ],
)
def test_each_candidate_rule_names_its_reason(change, reason):
    r = leaderboard.rank_vault(_vault(**change))
    assert r.why_not == [reason]


def test_age_floor_is_the_evaluation_evidence_floor():
    r = leaderboard.rank_vault(_vault(age_days=DEFAULT_LIMITS.min_age_days - 0.5))
    assert not r.candidate
    r = leaderboard.rank_vault(_vault(age_days=DEFAULT_LIMITS.min_age_days))
    assert r.candidate


# ---- board -----------------------------------------------------------------------------


def test_candidates_come_first_whatever_their_roi():
    young = _vault(address="0xa", name="young", age_days=2.0, pnl=800.0)  # 3,650 %/y
    steady = _vault(address="0xb", name="steady", pnl=100.0)  # 30 %/y
    board = leaderboard.rank([young, steady], sort="roi")
    assert [r.vault.name for r in board.vaults] == ["steady", "young"]
    assert [r.vault.name for r in board.candidates] == ["steady"]


@pytest.mark.parametrize("sort", leaderboard.SORTS)
def test_every_sort_orders_candidates(sort):
    a = _vault(address="0xa", name="a", pnl=100.0, apr=50.0, fee_apr=50.0, earning_30d=10.0)
    b = _vault(address="0xb", name="b", pnl=300.0, apr=900.0, fee_apr=900.0, earning_30d=900.0)
    board = leaderboard.rank([a, b], sort=sort)
    assert [r.vault.name for r in board.vaults] == ["b", "a"]
    assert board.owners[0].address == "0xowner"


def test_unknown_sort_is_an_error():
    with pytest.raises(ValueError):
        leaderboard.rank([_vault()], sort="tvl")


def test_owners_aggregate_their_losers_and_need_capital():
    win = _vault(address="0xa", name="win", owner="0x1", pnl=300.0, my_deposit=3_000.0)
    lose = _vault(address="0xb", name="lose", owner="0x1", pnl=-100.0, my_deposit=1_000.0)
    tiny = _vault(address="0xc", name="tiny", owner="0x2", pnl=60.0, my_deposit=100.0, tvl=100.0)
    board = leaderboard.rank([win, lose, tiny])
    assert [o.address for o in board.owners] == ["0x1"]  # 0x2: 100 $ deposited < 500
    o = board.owners[0]
    assert len(o.vaults) == 2 and abs(o.pnl - 200) < 1e-9 and abs(o.deposited - 4_000) < 1e-9
    assert abs(o.roi_pct - 5.0) < 1e-9 and o.best.vault.name == "win"


def test_owner_label_prefers_display_name():
    v = _vault(owner="0x" + "ab" * 20, owner_name="Uncle Bear", owner_verified="TWITTER")
    o = leaderboard.rank([v]).owners[0]
    assert o.label == "Uncle Bear" and o.verified == "TWITTER"
    o = leaderboard.rank([_vault(owner="0x" + "ab" * 20)]).owners[0]
    assert o.label == "0xabab…abab"


def test_board_from_the_live_shaped_fixture(offline):
    board = leaderboard.rank(fetch_public_vaults(4663))
    assert board.total == 6
    # Naabu2, Es RH bank, Vault Es raptor: old enough, funded, positive, agent on
    assert {r.vault.name for r in board.candidates} == {"Naabu2", "Es RH bank", "Vault Es raptor"}
    shroom = next(r for r in board.vaults if r.vault.name == "USDG/SHROOM Farm")
    assert shroom.why_not == ["age 3d < 14d", "no agent (nothing to copy)"]
    champ = next(r for r in board.vaults if r.vault.name == "Champ V3")
    assert champ.why_not == ["age 12d < 14d", "pnl -121"]
    es = next(o for o in board.owners if o.address.startswith("0xd8dea9"))
    assert len(es.vaults) == 2 and es.copies == 4


# ---- cli -------------------------------------------------------------------------------


def test_cli_prints_both_tables(offline, capsys):
    assert main(["vault-leaderboard", "--top", "3", "--sort", "pnl"]) == 0
    out = capsys.readouterr().out
    assert "owners" in out and "copy candidates of 6" in out
    assert "Naabu2" in out and "yes" in out
    assert "vault_review" not in out  # no review without --review


def test_cli_review_runs_the_evaluation_on_candidates(offline, monkeypatch, capsys):
    from krystal_curator import vault_eval, vault_review

    reviewed: list[str] = []

    class _Rv:
        pass

    class _Ev:
        verdict = "watch"
        reasons = ("fee record does not pay for price moves",)

    def fake_fetch_review(chain_id, address, **kw):
        reviewed.append(address)
        return _Rv()

    monkeypatch.setattr(vault_review, "fetch_review", fake_fetch_review)
    monkeypatch.setattr(vault_eval, "evaluate", lambda rv: _Ev())
    assert main(["vault-leaderboard", "--review", "2"]) == 0
    assert len(reviewed) == 2
    out = capsys.readouterr().out
    assert "review" in out and out.count("watch") >= 2
