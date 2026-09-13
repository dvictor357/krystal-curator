import time

from krystal_curator.models import Pool, Stat
from krystal_curator.monitor import Monitor
from krystal_curator.positions import Position
from krystal_curator.store import Store
from krystal_curator.vaults import Vault


def pool(addr="0xp", vol=2.0, dd=-1.0) -> Pool:
    return Pool(
        chain_id=4663,
        protocol="uniswapv4",
        address=addr,
        token0="ETH",
        token1="USDG",
        fee_tier_pct=0.3,
        tvl=1_000_000,
        s1h=Stat(volume=50_000, fee=150, apr=0),
        s24h=Stat(volume=1_000_000, fee=3_000, apr=0),
        s7d=Stat(volume=7e6, fee=21_000, apr=0),
        s30d=Stat(),
        drawdown24h=dd,
        volatility=vol,
        lp_auto=True,
        dynamic_fee=False,
        tag="",
    )


def position(status="IN_RANGE", cur=2500.0, pnl=0.0) -> Position:
    return Position(
        id="v:1",
        chain_id=4663,
        pool_address="0xp",
        protocol="uniswapv4",
        token0="ETH",
        token1="USDG",
        status=status,
        value=5000,
        deposit=5000,
        withdrawn=0,
        pnl=pnl,
        roi_pct=0,
        il=0,
        fee_pending=0,
        fee_claimed=0,
        reward_pending=0,
        fee_apr=0,
        total_apr=0,
        min_price=2000,
        max_price=3000,
        current_price=cur,
        opened_ts=int(time.time() - 86400),
        vault="V",
    )


def vault(*positions: Position) -> Vault:
    v = Vault(
        chain_id=4663,
        address="0xv",
        name="V",
        vault_type="autofarm",
        owned=True,
        tvl=6000,
        pnl=0,
        apr=0,
        fee_generated=0,
        earning_24h=0,
        earning_30d=0,
        risk="",
        age_days=1,
        my_value=6000,
        my_deposit=6000,
        my_withdrawn=0,
    )
    v.positions = list(positions)
    return v


def test_first_tick_reports_only_current_bad_state(tmp_path):
    m = Monitor(Store(tmp_path / "t.sqlite3"))
    alerts = m.tick([pool()], [vault(position())])
    assert alerts == []
    alerts = Monitor(Store(tmp_path / "u.sqlite3")).tick([pool()], [vault(position("OUT_RANGE"))])
    assert [a.title for a in alerts] == ["POSITION"] and "OUT OF RANGE" in alerts[0].text


def test_transitions(tmp_path):
    m = Monitor(Store(tmp_path / "t.sqlite3"))
    m.tick([pool()], [vault(position())])
    a = m.tick([pool()], [vault(position("OUT_RANGE"))])
    assert any(x.title == "POSITION" and "OUT OF RANGE" in x.text for x in a)
    a = m.tick([pool()], [vault(position())])
    assert any("back in range" in x.text for x in a)
    # edge: price 1% above the lower bound with σ 5%/d => 0.2σ
    a = m.tick([pool(vol=5.0)], [vault(position(cur=2020))])
    assert any(x.title == "EDGE" for x in a)
    a = m.tick([pool(vol=5.0)], [vault(position(cur=2020))])  # still critical: no repeat
    assert not any(x.title == "EDGE" for x in a)
    # pnl drop of 6% of value
    a = m.tick([pool(vol=5.0)], [vault(position(cur=2020, pnl=-300))])
    assert any(x.title == "PNL DROP" for x in a)


def test_pool_decay_alert(tmp_path):
    m = Monitor(Store(tmp_path / "t.sqlite3"))
    m.tick([pool(vol=2, dd=-1)], [vault(position())])  # grade A
    a = m.tick([pool(vol=60, dd=-55)], [vault(position())])  # grade collapses
    assert any(x.title == "POOL DECAY" for x in a)


def test_watchlist_alert_and_snapshots(tmp_path):
    st = Store(tmp_path / "t.sqlite3")
    p = pool()
    st.toggle_watch(p)
    m = Monitor(st)
    m.tick([p], None)
    assert st.history(p, hours=1)
    moved = pool()
    moved.tvl = 2_000_000  # +100 % tvl in an hour
    a = m.tick([moved], None)
    assert any(x.title == "WATCH ALERT" and "TVL +100%" in x.text for x in a)
