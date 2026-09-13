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
