"""robinhoodpools feed: field mapping, window degradation, paging, scoring of unknowns."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from krystal_curator import api, config, rhpools
from krystal_curator.models import Pool
from krystal_curator.profiles import PROFILES
from krystal_curator.scoring import curate, flags_for, passes

FIXTURE = Path(__file__).parent / "fixtures" / "rhpools_pools_robinhood.json"


@pytest.fixture(scope="module")
def recorded() -> dict:
    return json.loads(FIXTURE.read_text())


def _rows_by_id(recorded: dict) -> dict[str, dict[str, dict]]:
    by: dict[str, dict[str, dict]] = {}
    for window, page in recorded.items():
        for row in page.get("rows", []):
            by.setdefault(row["id"], {})[window] = row
    return by


def _transport(recorded: dict, *, page_size: int | None = None) -> httpx.MockTransport:
    """Serve the recorded pages; windows recorded as {"error": 503} answer 503."""
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        calls.append(q)
        page = recorded[q["window"]]
        if "error" in page:
            return httpx.Response(page["error"], json={"error": "aggregation timed out"})
        rows = page["rows"]
        if page_size is not None:
            off, lim = int(q.get("offset", 0)), int(q.get("limit", 50))
            rows = rows[off : off + min(lim, page_size)]
        return httpx.Response(200, json={**page, "rows": rows})

    t = httpx.MockTransport(handler)
    t.calls = calls  # type: ignore[attr-defined]
    return t


@pytest.fixture(autouse=True)
def _no_cooldown_carryover():
    rhpools._unavailable_until.clear()
    yield
    rhpools._unavailable_until.clear()


@pytest.fixture
def client_factory(monkeypatch):
    real = httpx.Client  # captured once: install() may run twice in one test

    def install(transport: httpx.MockTransport) -> None:
        monkeypatch.setattr(rhpools.httpx, "Client", lambda **kw: real(transport=transport, **kw))

    return install


# ---- mapping ------------------------------------------------------------


def test_from_rhpools_maps_fields(recorded):
    by = _rows_by_id(recorded)
    pid, rows = next((k, v) for k, v in by.items() if {"1h", "24h"} <= v.keys())
    p = Pool.from_rhpools(rows, chain_id=4663)
    r24 = rows["24h"]
    assert p.address == pid.lower() and p.source == "rhpools"
    assert p.protocol == {"v3": "uniswapv3", "v4": "uniswapv4"}[r24["protocol"]]
    assert p.fee_tier_pct == pytest.approx(r24["fee_ppm"] / 10_000)  # 10000 ppm == 1 %
    assert p.s24h.volume == pytest.approx(r24["volume_usd"])
    assert p.s24h.fee == pytest.approx(r24["fees_usd"])
    assert p.s1h.fee == pytest.approx(rows["1h"]["fees_usd"])
    assert p.tx24 == r24["swaps"]
    assert p.price == pytest.approx(r24["price"])
    assert p.risks == r24["risks"]
    # 7d / 30d were 503 in the recording → unknown, not zero
    assert {"stat7d", "stat30d", "volatility", "drawdown", "lp_auto"} <= p.unknown
    assert "stat1h" not in p.unknown and "stat24h" not in p.unknown
    assert p.s7d.fee == 0.0 and not p.is_new  # can't call it new without a week


def test_from_rhpools_tvl_falls_back_to_observed_active_value():
    row = {
        "id": "0xabc",
        "protocol": "v4",
        "token0": {"symbol": "ETH", "address": "0x0"},
        "token1": {"symbol": "USDG", "address": "0x1"},
        "fee_ppm": 3000,
        "tvl_usd": None,
        "observed_active_tvl_usd": 1234.5,
        "volume_usd": 10.0,
        "fees_usd": 0.03,
        "swaps": 3,
        "price": 1.0,
    }
    p = Pool.from_rhpools({"24h": row}, chain_id=4663)
    assert p.tvl == pytest.approx(1234.5)
    assert p.tvl_basis == "observed active liquidity value"
    assert "tvl" not in p.unknown
    none = Pool.from_rhpools({"24h": {**row, "observed_active_tvl_usd": None}}, chain_id=4663)
    assert none.tvl == 0.0 and "tvl" in none.unknown
    assert passes(none, PROFILES["degen"]) == "tvl unknown"


def test_from_rhpools_dynamic_fee_when_ppm_missing():
    row = {"id": "0x1", "protocol": "v4", "fee_ppm": None, "tvl_usd": 1.0, "swaps": 0}
    p = Pool.from_rhpools({"24h": row}, chain_id=4663)
    assert p.dynamic_fee and p.fee_tier_pct == 0.0 and p.tx24 == 0 and p.price is None


# ---- fetching -----------------------------------------------------------


def test_fetch_pools_drops_503_windows_and_marks_unknown(recorded, client_factory):
    t = _transport(recorded)
    client_factory(t)
    pools = rhpools.fetch_pools(4663, base="http://rh.test/", top=12, windows=rhpools.WINDOWS)
    assert len(pools) == len(recorded["24h"]["rows"])
    assert {c["window"] for c in t.calls} == {"1h", "24h", "7d", "30d"}
    assert all("stat7d" in p.unknown and "stat30d" in p.unknown for p in pools)
    in_1h = {r["id"] for r in recorded["1h"]["rows"]}
    for p in pools:
        assert ("stat1h" in p.unknown) == (p.address not in in_1h)


def test_fetch_pools_pages_until_top_or_short_page(recorded, client_factory, monkeypatch):
    monkeypatch.setattr(rhpools, "PAGE", 5)  # pretend the server caps pages at 5
    t = _transport(recorded, page_size=5)
    client_factory(t)
    pools = rhpools.fetch_pools(4663, base="http://rh.test", top=12)
    offsets = sorted(int(c["offset"]) for c in t.calls if c["window"] == "24h")
    assert offsets == [0, 5, 10]  # 12 rows, 5 per page: 5, 5, 2 → top reached
    assert len(pools) == 12
    assert max(int(c["limit"]) for c in t.calls) <= 5
    # a short page ends the walk before `top`
    t2 = _transport(recorded, page_size=5)
    client_factory(t2)
    rhpools.fetch_pools(4663, base="http://rh.test", top=100)
    assert sorted(int(c["offset"]) for c in t2.calls if c["window"] == "24h") == [0, 5, 10]


def test_failed_window_is_not_retried_during_cooldown(recorded, client_factory, monkeypatch):
    t = _transport(recorded)
    client_factory(t)
    kw = {"base": "http://rh.test", "top": 12, "windows": rhpools.WINDOWS}
    rhpools.fetch_pools(4663, **kw)
    first = len([c for c in t.calls if c["window"] in ("7d", "30d")])
    assert first == 2
    rhpools.fetch_pools(4663, **kw)
    assert len([c for c in t.calls if c["window"] in ("7d", "30d")]) == first  # skipped
    # public host: an hour, not ten minutes — each retry costs the operator ~15 s
    clock = time.monotonic() + rhpools.LOCAL_UNAVAILABLE_COOLDOWN_S + 1
    monkeypatch.setattr(rhpools.time, "monotonic", lambda: clock)
    rhpools.fetch_pools(4663, **kw)
    assert len([c for c in t.calls if c["window"] in ("7d", "30d")]) == first  # still skipped
    clock = time.monotonic() + rhpools.UNAVAILABLE_COOLDOWN_S + 1
    rhpools.fetch_pools(4663, **kw)
    assert len([c for c in t.calls if c["window"] in ("7d", "30d")]) == first + 2  # retried


# ---- politeness on the shared instance -----------------------------------


def test_public_host_asks_for_short_windows_only_one_page_sequentially(recorded, client_factory):
    t = _transport(recorded)
    client_factory(t)
    pools = rhpools.fetch_pools(4663, base="https://rhpools.lol")
    assert {c["window"] for c in t.calls} == {"1h", "24h"}  # never 7d / 30d
    assert all(int(c["limit"]) <= rhpools.PAGE and c["offset"] == "0" for c in t.calls)
    assert len(t.calls) == 2  # one page each
    assert pools and all({"stat7d", "stat30d"} <= p.unknown for p in pools)
    assert not rhpools.is_local("https://rhpools.lol") and not rhpools.is_local(
        "http://10.0.0.5:8196"
    )


def test_local_host_asks_for_every_window(recorded, client_factory):
    t = _transport(recorded)
    client_factory(t)
    rhpools.fetch_pools(4663, base="http://127.0.0.1:8196", top=12)
    assert {c["window"] for c in t.calls} == set(rhpools.WINDOWS)
    for base in ("http://localhost:8196", "http://127.0.0.1:8196/", "http://[::1]:8196"):
        assert rhpools.is_local(base), base


def test_explicit_windows_override_and_always_include_24h(recorded, client_factory):
    t = _transport(recorded)
    client_factory(t)
    rhpools.fetch_pools(4663, base="https://rhpools.lol", windows=["1h"])
    assert {c["window"] for c in t.calls} == {"1h", "24h"}
    t2 = _transport(recorded)
    client_factory(t2)
    rhpools.fetch_pools(4663, base="https://rhpools.lol", windows=["7d", "30d", "24h"])
    assert {c["window"] for c in t2.calls} == {"24h", "7d", "30d"}


def test_local_cooldown_is_shorter(recorded, client_factory, monkeypatch):
    t = _transport(recorded)
    client_factory(t)
    rhpools.fetch_pools(4663, base="http://127.0.0.1:8196", top=12)
    n = len([c for c in t.calls if c["window"] == "7d"])
    clock = time.monotonic() + rhpools.LOCAL_UNAVAILABLE_COOLDOWN_S + 1
    monkeypatch.setattr(rhpools.time, "monotonic", lambda: clock)
    rhpools.fetch_pools(4663, base="http://127.0.0.1:8196", top=12)
    assert len([c for c in t.calls if c["window"] == "7d"]) == n + 1


def test_fetch_pools_fails_without_24h(recorded, client_factory):
    broken = {**recorded, "24h": {"error": 503}}
    client_factory(_transport(broken))
    with pytest.raises(rhpools.RhpoolsError, match="24h window unavailable"):
        rhpools.fetch_pools(4663, base="http://rh.test")


def test_fetch_pools_rejects_other_chains():
    with pytest.raises(rhpools.RhpoolsError, match="4663 only"):
        rhpools.fetch_pools(8453)


def test_fetch_pools_non_503_error_propagates(recorded, client_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client_factory(httpx.MockTransport(handler))
    with pytest.raises(rhpools.RhpoolsError, match="500"):
        rhpools.fetch_pools(4663, base="http://rh.test")


# ---- dispatch + config ---------------------------------------------------


def test_api_dispatch(recorded, client_factory, monkeypatch):
    client_factory(_transport(recorded))
    pools = api.fetch_pools(4663, source="rhpools", rhpools_url="http://rh.test", rhpools_top=12)
    assert pools and all(p.source == "rhpools" for p in pools)
    with pytest.raises(api.KrystalError, match="4663 only"):
        api.fetch_pools(8453, source="rhpools")
    with pytest.raises(api.KrystalError, match="unknown pool source"):
        api.fetch_pools(4663, source="dune")
    called = {}
    monkeypatch.setattr(api, "fetch_krystal_pools", lambda c, **kw: called.setdefault("c", c) or [])
    api.fetch_pools(4663)
    assert called["c"] == 4663


def test_config_source_env_and_kwargs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(config.CONFIG_ENV, raising=False)
    monkeypatch.setenv("KRYSTAL_SOURCE", "rhpools")
    monkeypatch.setenv("KRYSTAL_RHPOOLS_URL", "http://127.0.0.1:8196")
    monkeypatch.setenv("KRYSTAL_RHPOOLS_WINDOWS", "1h,24h,7d")
    cfg = config.load()
    assert cfg.fetch_kwargs == {
        "source": "rhpools",
        "rhpools_url": "http://127.0.0.1:8196",
        "rhpools_top": 150,
        "rhpools_windows": ["1h", "24h", "7d"],
    }


# ---- scoring with unknown metrics ---------------------------------------


def test_scoring_treats_unknowns_as_neutral_not_safe(recorded):
    by = _rows_by_id(recorded)
    pools = [Pool.from_rhpools(v, chain_id=4663) for v in by.values() if "24h" in v]
    scored = curate(pools, PROFILES["balanced"], quote=None)
    assert scored, "unknown σ / lp_auto must not filter every chain-indexed pool"
    for s in scored:
        assert 0 < s.score < 100
        assert s.parts["risk"] == pytest.approx(0.5)  # unknown σ and drawdown → mid
        assert s.parts["consistency"] == pytest.approx(0.5)  # no 7d window → neutral
        assert s.grade in "BCDE"  # never "A" on unknown risk inputs
        assert "σ?" in s.flags and "7D?" in s.flags
        assert not {"NO-AUTO", "SPIKE", "FADING"} & set(s.flags)  # need data we don't have
    # yield haircut without a weekly window (0.75× instead of min(24h, 7d))
    p = scored[0].pool
    assert scored[0].parts["yield"] > 0 and p.fee_yield_7d_daily == 0.0


def test_flags_quiet_1h_needs_a_served_1h_window():
    row = {
        "id": "0x1",
        "protocol": "v3",
        "fee_ppm": 3000,
        "tvl_usd": 1e6,
        "volume_usd": 5e5,
        "fees_usd": 1500.0,
        "swaps": 10,
        "price": 2.0,
    }
    without_1h = Pool.from_rhpools({"24h": row}, chain_id=4663)
    assert "QUIET-1H" not in flags_for(without_1h)
    with_quiet_1h = Pool.from_rhpools(
        {"24h": row, "1h": {**row, "volume_usd": 0.0, "fees_usd": 0.0}}, chain_id=4663
    )
    assert "QUIET-1H" in flags_for(with_quiet_1h)
