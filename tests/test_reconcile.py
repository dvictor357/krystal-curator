"""Cross-feed reconciliation: matching, deltas, severity, and the SRCΔ column."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from krystal_curator import api
from krystal_curator.models import Pool, Stat
from krystal_curator.profiles import PROFILES
from krystal_curator.reconcile import NOTE_PCT, WARN_PCT, Recon, reconcile
from krystal_curator.scoring import curate

FIXTURE = Path(__file__).parent / "fixtures" / "top_pools_robinhood.json"


def _pool(address: str, *, source: str, tvl: float, vol: float, fee: float, **kw) -> Pool:
    return Pool(
        chain_id=4663,
        protocol="uniswapv4",
        address=address,
        token0="ETH",
        token1="USDG",
        fee_tier_pct=0.3,
        tvl=tvl,
        s1h=Stat(),
        s24h=Stat(volume=vol, fee=fee),
        s7d=Stat(volume=vol * 7, fee=fee * 7),
        s30d=Stat(),
        drawdown24h=0.0,
        volatility=0.0,
        lp_auto=True,
        dynamic_fee=False,
        tag="",
        source=source,
        **kw,
    )


def test_reconcile_matches_on_address_and_reports_deltas():
    primary = [
        _pool("0xa", source="krystal", tvl=100.0, vol=1000.0, fee=10.0),
        _pool("0xb", source="krystal", tvl=100.0, vol=1000.0, fee=10.0),
        _pool("0xc", source="krystal", tvl=100.0, vol=1000.0, fee=10.0),
    ]
    other = [
        _pool("0xa", source="chain", tvl=110.0, vol=1250.0, fee=9.0),
        _pool("0xb", source="chain", tvl=103.0, vol=1000.0, fee=10.0),
        _pool("0xz", source="chain", tvl=1.0, vol=1.0, fee=1.0),
    ]
    rec = reconcile(primary, other)
    assert rec.other == "chain"
    assert set(rec.by_address) == {"0xa", "0xb"}
    assert rec.primary_only == 1 and rec.other_only == 1
    a = rec.by_address["0xa"]
    assert a.tvl_pct == pytest.approx(10.0)
    assert a.vol24_pct == pytest.approx(25.0)
    assert a.fee24_pct == pytest.approx(-10.0)
    assert a.worst == pytest.approx(25.0) and a.level == "warn"
    assert a.headline == "+10%" and a.describe() == "vs chain: tvl +10%  vol24 +25%  fee24 -10%"
    b = rec.by_address["0xb"]
    assert b.level == "ok" and b.worst == pytest.approx(3.0)
    assert rec.flagged == 1
    assert rec.summary() == "vs chain: 2 matched, 1 ≥15% off, 1 only here, 1 only there"


def test_unknown_or_zero_tvl_is_not_compared():
    primary = [_pool("0xa", source="krystal", tvl=100.0, vol=1000.0, fee=10.0)]
    unknown = _pool(
        "0xa", source="chain", tvl=0.0, vol=1100.0, fee=10.0, unknown=frozenset({"tvl"})
    )
    r = reconcile(primary, [unknown]).by_address["0xa"]
    assert r.tvl_pct is None and r.vol24_pct == pytest.approx(10.0)
    assert r.headline == "+10%v" and r.level == "note"
    zero = _pool("0xa", source="chain", tvl=0.0, vol=0.0, fee=0.0)
    r0 = reconcile(primary, [zero]).by_address["0xa"]
    assert r0.deltas == {} and r0.worst is None and r0.level == "none" and r0.headline == "?"


def test_levels_follow_thresholds():
    assert Recon("x", NOTE_PCT - 0.1, None, None).level == "ok"
    assert Recon("x", NOTE_PCT, None, None).level == "note"
    assert Recon("x", -WARN_PCT, None, None).level == "warn"


def test_curate_attaches_recon():
    rows = json.loads(FIXTURE.read_text())["result"]
    pools = [Pool.from_public(x) for x in rows]
    other = [
        _pool(p.address, source="chain", tvl=p.tvl * 1.3, vol=p.s24h.volume, fee=p.s24h.fee)
        for p in pools[:5]
    ]
    rec = reconcile(pools, other)
    scored = curate(pools, PROFILES["degen"], quote=None, recon=rec)
    with_recon = [s for s in scored if s.recon]
    assert with_recon and all(s.recon.tvl_pct == pytest.approx(30.0) for s in with_recon)
    assert all(s.recon is None for s in curate(pools, PROFILES["degen"], quote=None))


def test_reference_source_is_dormant_without_a_second_feed(monkeypatch):
    # One feed today: nothing to reconcile against on any chain, and no fetch is attempted.
    assert api.reference_source(4663, "krystal") is None
    assert api.reference_source(8453, "krystal") is None
    monkeypatch.setattr(api, "fetch_pools", lambda c, **kw: pytest.fail("must not fetch"))
    assert api.fetch_reference_pools(4663, source="krystal") is None
