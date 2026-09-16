import time

from krystal_curator.models import Pool, Stat
from krystal_curator.store import Store, sparkline


def mk(addr: str, tvl: float, fee: float) -> Pool:
    return Pool(
        chain_id=4663,
        protocol="uniswapv4",
        address=addr,
        token0="USDG",
        token1="X",
        fee_tier_pct=0.3,
        tvl=tvl,
        s1h=Stat(),
        s24h=Stat(volume=fee * 100, fee=fee, apr=0),
        s7d=Stat(),
        s30d=Stat(),
        drawdown24h=-1,
        volatility=5,
        lp_auto=True,
        dynamic_fee=False,
        tag="",
    )


def test_snapshots_history_and_delta(tmp_path):
    st = Store(tmp_path / "t.sqlite3")
    now = int(time.time())
    st.record([mk("0xa", 100_000, 1_000)], ts=now - 25 * 3600)
    st.record([mk("0xa", 110_000, 1_200)], ts=now - 12 * 3600)
    st.record([mk("0xa", 120_000, 1_500)], ts=now)
    hist = st.history(mk("0xa", 0, 0), hours=48)
    assert [h.tvl for h in hist] == [100_000, 110_000, 120_000]
    d = st.delta(mk("0xa", 120_000, 1_500), hours=24)
    assert d.hours is not None and 24 < d.hours < 26
    assert abs(d.tvl_pct - 20) < 1e-9
    assert abs(d.fee24_pct - 50) < 1e-9
    assert st.delta(mk("0xzz", 1, 1)).tvl_pct is None


def test_delta_skips_current_refresh(tmp_path):
    st = Store(tmp_path / "t.sqlite3")
    now = int(time.time())
    st.record([mk("0xa", 100_000, 1_000)], ts=now - 3600)
    st.record([mk("0xa", 150_000, 1_000)], ts=now)  # just refreshed
    d = st.delta(mk("0xa", 150_000, 1_000), hours=24)
    assert abs(d.tvl_pct - 50) < 1e-9  # compared against the hour-old row, not itself


def test_watchlist_persists(tmp_path):
    p = mk("0xa", 1, 1)
    st = Store(tmp_path / "t.sqlite3")
    assert st.toggle_watch(p) is True
    assert st.is_watched(p)
    st2 = Store(tmp_path / "t.sqlite3")
    assert st2.is_watched(p)
    assert st2.toggle_watch(p) is False
    assert not Store(tmp_path / "t.sqlite3").is_watched(p)


def test_sparkline():
    assert sparkline([]) == ""
    assert sparkline([1, 1, 1]) == "▄▄▄"
    s = sparkline([0, 1, 2, 3, 4, 5, 6, 7])
    assert s == "▁▂▃▄▅▆▇█"
    assert len(sparkline(list(range(50)), width=12)) == 12


def test_mark_seen_keeps_first_timestamp(tmp_path):
    st = Store(tmp_path / "t.sqlite3")
    p = mk("0xa", 1, 1)
    st.mark_seen([p])
    first = p.first_seen_ts
    assert first > 0
    time.sleep(1.1)
    q = mk("0xa", 2, 2)
    st.mark_seen([q, mk("0xb", 1, 1)])
    assert q.first_seen_ts == first


def test_price_recorded_and_series(tmp_path):
    st = Store(tmp_path / "p.sqlite3")
    now = int(time.time())
    p = mk("0xa", 100_000, 1_000)
    p.price0_usd, p.price1_usd = 2.0, 1.0
    st.record([p], ts=now - 600)
    p.price0_usd = 2.2
    st.record([p], ts=now)
    st.record([mk("0xb", 100_000, 1_000)], ts=now)  # no price → excluded
    series = st.price_series(4663, days=1)
    assert list(series) == ["0xa:uniswapv4"]
    assert [(ts, price) for ts, price, _ in series["0xa:uniswapv4"]] == [
        (now - 600, 2.0),
        (now, 2.2),
    ]
    assert series["0xa:uniswapv4"][0][2] == 5  # volatility rides along


def test_price_column_migrated_on_old_db(tmp_path):
    import sqlite3

    db = tmp_path / "old.sqlite3"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE snapshots (ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, "
        "address TEXT NOT NULL, protocol TEXT NOT NULL, tvl REAL, vol24 REAL, fee24 REAL, "
        "vol1h REAL, fee1h REAL, fee7d REAL, apr24 REAL, volatility REAL, drawdown REAL);"
        "INSERT INTO snapshots VALUES (1,4663,'0xa','uniswapv4',1,1,1,1,1,1,1,1,1);"
    )
    con.commit()
    con.close()
    st = Store(db)
    st.record([mk("0xa", 100_000, 1_000)])  # 14-column insert works after migration
    assert st.price_series(4663, days=1) == {}  # old row and unpriced row both excluded
    assert len(st.all_snapshots(days=1e6)) == 2
