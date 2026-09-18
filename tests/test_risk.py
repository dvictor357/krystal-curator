"""Realised σ / drawdown filled from local snapshots for feeds that report none."""

from __future__ import annotations

import math
import random

import pytest

from krystal_curator import risk
from krystal_curator.models import Pool, Stat
from krystal_curator.profiles import PROFILES
from krystal_curator.scoring import flags_for, passes
from krystal_curator.store import Store

NOW = 1_800_000_000


def _pool(
    address: str, *, unknown=("volatility", "drawdown", "lp_auto"), price: float = 100.0
) -> Pool:
    p = Pool(
        chain_id=4663,
        protocol="uniswapv3",
        address=address,
        token0="USDG",
        token1="X",
        fee_tier_pct=0.3,
        tvl=1e6,
        s1h=Stat(),
        s24h=Stat(volume=2e6, fee=1500.0),
        s7d=Stat(),
        s30d=Stat(),
        drawdown24h=0.0,
        volatility=0.0,
        lp_auto=False,
        dynamic_fee=False,
        tag="",
        price_t0_in_t1=price,
        unknown=frozenset(unknown),
    )
    return p


def _record_walk(store: Store, p: Pool, *, sigma_day: float, hours: float, step: int = 900):
    """15-min snapshots of a log-normal walk with a known daily σ, ending at NOW."""
    rng = random.Random(11)
    n = int(hours * 3600 / step)
    price = p.price
    ts = NOW - n * step
    for _ in range(n + 1):
        p.price_t0_in_t1 = price
        store.record([p], ts=ts)
        price *= math.exp(rng.gauss(0, sigma_day * math.sqrt(step / 86400)))
        ts += step


def test_fills_sigma_and_drawdown_from_history(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.sqlite3")
    monkeypatch.setattr(risk.time, "time", lambda: NOW)
    monkeypatch.setattr("krystal_curator.store.time.time", lambda: NOW)
    p = _pool("0xaaa")
    _record_walk(store, p, sigma_day=0.05, hours=7 * 24)
    fresh = _pool("0xaaa")
    assert passes(fresh, PROFILES["conservative"]) is None  # σ unknown → not filtered
    assert "σ?" in flags_for(fresh)
    assert risk.fill_realised_risk([fresh], store) == 1
    assert fresh.unknown == frozenset({"lp_auto"})
    assert abs(fresh.volatility - 5.0) < 0.7
    assert fresh.volatility_basis.startswith("realised over 7.0d")
    assert fresh.drawdown24h <= 0.0 and fresh.drawdown24h > -30
    assert "σ~" in flags_for(fresh) and "σ?" not in flags_for(fresh)
    # now the conservative cap (σ ≤ 15) applies again on real numbers
    fresh.volatility = 40.0
    assert passes(fresh, PROFILES["conservative"]) == "volatility 40 > 15"


def test_short_history_stays_unknown(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.sqlite3")
    monkeypatch.setattr(risk.time, "time", lambda: NOW)
    monkeypatch.setattr("krystal_curator.store.time.time", lambda: NOW)
    p = _pool("0xbbb")
    _record_walk(store, p, sigma_day=0.05, hours=3)  # 12 points over 3 h
    fresh = _pool("0xbbb")
    assert risk.fill_realised_risk([fresh], store) == 0
    assert fresh.unknown == frozenset({"volatility", "drawdown", "lp_auto"})
    assert fresh.volatility == 0.0 and not fresh.volatility_basis
    # drawdown needs 6 h; σ needs 12 h: at 8 h only drawdown is known
    _record_walk(store, _pool("0xccc"), sigma_day=0.05, hours=8)
    part = _pool("0xccc")
    assert risk.fill_realised_risk([part], store) == 1
    assert part.unknown == frozenset({"volatility", "lp_auto"})


def test_reported_values_are_never_overwritten(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.sqlite3")
    monkeypatch.setattr(risk.time, "time", lambda: NOW)
    monkeypatch.setattr("krystal_curator.store.time.time", lambda: NOW)
    reported = _pool("0xddd", unknown=())
    reported.volatility, reported.drawdown24h = 33.0, -12.0
    _record_walk(store, reported, sigma_day=0.05, hours=48)
    again = _pool("0xddd", unknown=())
    again.volatility, again.drawdown24h = 33.0, -12.0
    assert risk.fill_realised_risk([again], store) == 0
    assert (again.volatility, again.drawdown24h) == (33.0, -12.0)
    assert "σ~" not in flags_for(again)


def test_max_drawdown_is_peak_to_trough():
    series = [
        (NOW - 6 * 3600 + i * 3600, p, 0.0) for i, p in enumerate([100, 120, 90, 110, 80, 100, 100])
    ]
    assert risk.max_drawdown_pct(series, since=NOW - 86400) == pytest.approx(80 / 120 * 100 - 100)
    assert risk.max_drawdown_pct(series[:3], since=NOW - 86400) is None  # < 4 points
    assert risk.max_drawdown_pct(series, since=NOW - 3600) is None  # window too short
    rising = [(NOW - 6 * 3600 + i * 3600, 100 + i, 0.0) for i in range(7)]
    assert risk.max_drawdown_pct(rising, since=NOW - 86400) == 0.0


def test_monitor_tick_fills_before_alerts(tmp_path, monkeypatch):
    from krystal_curator.monitor import Monitor

    monkeypatch.setattr(risk.time, "time", lambda: NOW)
    monkeypatch.setattr("krystal_curator.store.time.time", lambda: NOW)
    monkeypatch.setattr("krystal_curator.monitor.time.time", lambda: NOW)
    store = Store(tmp_path / "t.sqlite3")
    p = _pool("0xeee")
    _record_walk(store, p, sigma_day=0.05, hours=24)
    mon = Monitor(store, profile=PROFILES["balanced"])
    live = _pool("0xeee")
    mon.tick([live], None)
    assert "volatility" not in live.unknown and live.volatility > 0
    # the snapshot written by this tick keeps the feed's own (unknown → 0) σ so that
    # `backtest --sigma` never compares realised against realised
    latest = store.history(live, hours=1)[0]
    assert latest.volatility == 0.0
