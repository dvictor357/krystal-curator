"""vault-review: one public vault, read from four endpoints, written down with provenance."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from krystal_curator import net
from krystal_curator import vault_review as vr
from krystal_curator.api import KrystalError

FIX = Path(__file__).parent / "fixtures" / "vault_review"
CHAIN, ADDR = 4663, "0xd674495c331b4e059b67745b51eef7b960f41451"
URL = f"https://defi.krystal.app/vaults/{CHAIN}/{ADDR}"


def _fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def _route(url: str, params: dict | None) -> tuple[int, object]:
    params = params or {}
    if url.endswith(f"/vaults/{CHAIN}/{ADDR}"):
        return 200, _fixture("detail.json")
    if url.endswith("/vault-agent-settings"):
        return 200, _fixture("settings.json")
    if url.endswith("/auto-farming-action-plans"):
        return 200, _fixture("plans.json")
    if "/vaults/performance/" in url:
        tf = params.get("timeframe")
        if tf in ("24h", "30d"):
            return 200, _fixture(f"perf_{tf}.json")
        return 200, {"data": []}
    return 404, {"error": "route not found"}


@pytest.fixture
def offline(monkeypatch):
    """Serve the fixtures through `net.get`; `broken` names endpoints that 5xx."""
    broken: set[str] = set()
    calls: list[str] = []

    def fake_get(url, *, params=None, **kw):
        calls.append(url)
        status, body = _route(url, params)
        if any(b in url for b in broken):
            status, body = 502, {"error": "bad gateway"}
        req = httpx.Request("GET", url, params=params)
        return httpx.Response(status, json=body, request=req)

    monkeypatch.setattr(net, "get", fake_get)
    return broken, calls


# ---- URL -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        URL,
        URL + "?r=35STGKW0",
        f"{CHAIN}/{ADDR}",
        f"https://www.defi.krystal.app/vaults/{CHAIN}/0x{ADDR[2:].upper()}",
    ],
)
def test_parse_vault_url_accepts_krystal_forms(text):
    assert vr.parse_vault_url(text) == (CHAIN, ADDR)


@pytest.mark.parametrize(
    "text",
    [
        "https://evil.example/vaults/4663/" + ADDR,  # other host
        "http://defi.krystal.app/vaults/4663/" + ADDR,  # not https
        "https://defi.krystal.app/pools/4663/" + ADDR,  # not a vault path
        "https://defi.krystal.app/vaults/abc/" + ADDR,  # chain not an int
        "https://defi.krystal.app/vaults/4663/0x1234",  # short address
        "4663/" + ADDR[:-1] + "zz",  # not hex
    ],
)
def test_parse_vault_url_rejects_everything_else(text):
    with pytest.raises(vr.VaultUrlError):
        vr.parse_vault_url(text)


# ---- parsing ---------------------------------------------------------------------


def test_settings_parse_matches_ui_fields():
    s = vr.parse_settings(_fixture("settings.json"))
    assert s.goal.startswith("Maximize USD-denominated vault value")
    assert s.permissions == ["swap_and_mint", "swap_and_increase", "adjust_range", "harvest"]
    assert s.minimum_range_pct == 5 and s.minimum_tvl == 1000 and s.whitelisted_pools == []
    assert s.execution.interval_s == 1800 and s.execution.swap_slippage == 0.02
    assert s.execution.max_gas_fee_ceiling == 1.3 and s.execution.max_gas_fee_ceiling_unit == "$"
    assert s.execution.max_value_per_strategy_text == "15% of TVL"
    assert s.risk_level == "high_risk" and s.target_token_type == "stable"
    assert "Exiting positions is strictly forbidden" in s.instructions


def test_settings_missing_fields_stay_unknown():
    s = vr.parse_settings({"autoFarmingConfig": {"permissions": ["harvest"]}})
    assert s.minimum_range_pct is None and s.minimum_tvl is None
    assert s.enabled is None and s.execution.interval_s is None
    assert s.execution.max_value_per_strategy_text == "unknown"


def test_plan_stats_count_statuses_actions_and_collapse_errors():
    plans = [vr.parse_plan(r) for r in _fixture("plans.json")["data"]]
    st = vr.plan_stats(plans, 711)
    assert st.total == 711 and st.fetched == 6
    assert st.by_status == {"success": 3, "failed": 2, "partial_success": 1}
    assert st.failure_rate == pytest.approx(2 / 6)
    assert sum(st.by_action.values()) == sum(len(p.actions) for p in plans)
    # the two gas-cap errors differ only in their dollar amounts → one key, count 2
    assert list(st.errors.values()) == [2]
    assert st.oldest < st.newest


def test_perf_series_rederives_fee_apr_on_time_weighted_tvl():
    ps = vr.parse_perf("30d", _fixture("perf_30d.json"))
    assert len(ps.points) == 17 and ps.span_s > 0
    assert ps.fee_sum == pytest.approx(sum(p.fee_earned for p in ps.points))
    weighted = sum(p.tvl * p.duration_s for p in ps.points) / ps.span_s
    assert ps.avg_tvl == pytest.approx(weighted)
    assert ps.fee_apr_pct == pytest.approx(ps.fee_sum / weighted * 365 * 86400 / ps.span_s * 100)
    assert ps.feed_apr_pct == pytest.approx(ps.points[-1].apr * 100)
    assert not ps.share_price_known  # sharePriceUsd is 0 throughout → no NAV series


def test_perf_series_empty_is_unknown_not_zero():
    ps = vr.parse_perf("7d", {"data": []})
    assert ps.avg_tvl is None and ps.fee_apr_pct is None and ps.feed_apr_pct is None


# ---- the review ------------------------------------------------------------------


def test_fetch_review_reads_every_source_and_flags_the_source_vault(offline):
    rv = vr.fetch_review(CHAIN, ADDR)
    assert rv.vault is not None and rv.vault.name == "TH 33 and 9 RH (copy)"
    assert rv.vault.agent_activated and not rv.vault.allow_deposit
    assert "POOL_LIST_CUSTOM" in rv.vault.securities
    assert len(rv.vault.positions) == 3 and len(rv.vault.closed) == 6
    assert rv.served == {
        "detail": "ok",
        "settings": "ok",
        "plans": "ok",
        "performance 24h": "ok",
        "performance 7d": "ok",
        "performance 30d": "ok",
    }
    keys = {o.key: o for o in rv.observations}
    # acceptance: high APR but no exit → flagged from the *platform* permissions
    assert keys["exit_not_permitted"].level == "warn"
    assert keys["exit_not_permitted"].basis == "platform"
    assert keys["exit_forbidden_in_text"].basis == "instructions"
    assert keys["range_floor_below_ours"].basis == "platform"
    assert "±5%" in keys["range_target_below_ours"].text
    assert "apr_chasing" in keys
    assert "USDT" in keys["quote_mismatch"].text and "USDG" in keys["quote_mismatch"].text
    assert "USDG/MICRODUCK×2" in keys["rebalance_series"].text
    assert "ETH/PAR×2" in keys["rebalance_series"].text
    assert keys["plan_failures"].text.startswith("2/6")
    # fixture 24h buckets sum 199.81 vs earning24h 190.59: within 10 % → fact, not warn
    assert keys["fee_24h_consistency"].level == "fact"
    assert any("beyond the newest 6 of 711" in m for m in rv.missing)
    assert any("NAV per share" in m for m in rv.missing)


def test_pending_fees_are_not_added_twice(offline):
    rv = vr.fetch_review(CHAIN, ADDR)
    v = rv.vault
    # fees_total per position = feeGenerated (which already contains pending), never more
    for p in v.positions + v.closed:
        assert p.fees_total <= p.fee_claimed + p.fee_pending + 1e-9
        assert p.fee_claimed >= 0
    text = next(o.text for o in rv.observations if o.key == "fee_pending_included")
    assert f"{v.fee_generated:,.2f}$" in text


def test_partial_api_is_recorded_not_fatal(offline):
    broken, _ = offline
    broken.update({"vault-agent-settings", "auto-farming-action-plans", "/performance/"})
    rv = vr.fetch_review(CHAIN, ADDR)
    assert rv.vault is not None and rv.settings is None and rv.plan_stats is None
    assert rv.perf == {}
    assert rv.served["settings"].startswith("vault-agent-settings: HTTP 502")
    assert any("agent settings" in m for m in rv.missing)
    assert any("action-plan history" in m for m in rv.missing)
    assert any("performance series 7d" in m for m in rv.missing)
    keys = {o.key for o in rv.observations}
    assert "exit_not_permitted" not in keys  # no settings → no claim about them
    md = vr.to_markdown(rv)
    assert "settings=FAILED" in md and "## Agent settings" not in md


def test_detail_failure_is_fatal(offline):
    broken, _ = offline
    broken.add(f"/vaults/{CHAIN}/{ADDR}")
    with pytest.raises(KrystalError):
        vr.fetch_review(CHAIN, ADDR)


def test_reports_are_written_dated_with_provenance(offline, tmp_path):
    rv = vr.fetch_review(CHAIN, ADDR, plans_limit=6)
    md, js = vr.write_review(rv, tmp_path / "reports")
    assert md.name.startswith(f"vault_review_{CHAIN}_{ADDR[:10]}_") and md.suffix == ".md"
    text = md.read_text()
    assert "Exiting positions is strictly forbidden" in text  # quoted verbatim
    assert "data, not directions" in text
    assert "| USDG/RCAT | IN_RANGE |" in text
    assert "unknown" not in text.split("## Open positions")[1].split("## Closed")[0]
    data = json.loads(js.read_text())
    assert data["url"].startswith(URL + "?r=") and data["served"]["detail"] == "ok"
    assert data["settings"]["minimum_range_pct"] == 5
    assert data["raw"]["settings"]["goal"] == rv.settings.goal
    assert "vaultData" not in json.dumps(data["raw"]["plans"])  # heavy snapshot stripped
    assert data["perf_derived"]["30d"]["fee_apr_pct"] == pytest.approx(rv.perf["30d"].fee_apr_pct)
    lean = json.loads(vr.to_json(rv, raw=False))
    assert "raw" not in lean


def test_cli_vault_review_writes_and_exits_zero(offline, tmp_path, capsys):
    from krystal_curator.cli import main

    rc = main(["vault-review", URL, "--out", str(tmp_path), "--quiet", "--plans", "6"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "wrote" in out and list(tmp_path.glob("vault_review_*.md"))


def test_cli_rejects_foreign_url(tmp_path, capsys):
    from krystal_curator.cli import main

    rc = main(["vault-review", "https://example.com/vaults/4663/" + ADDR, "--out", str(tmp_path)])
    assert rc == 2 and not list(tmp_path.iterdir())
