import time

from krystal_curator.models import Pool, Stat
from krystal_curator.positions import Position
from krystal_curator.profiles import PROFILES
from krystal_curator.rotation import plan


def pool(addr: str, sym: str, tvl: float, fee24: float, vol: float = 10) -> Pool:
    return Pool(
        chain_id=4663,
        protocol="uniswapv4",
        address=addr,
        token0="USDG",
        token1=sym,
        fee_tier_pct=0.3,
        tvl=tvl,
        s1h=Stat(volume=fee24 * 4, fee=fee24 / 24, apr=0),
        s24h=Stat(volume=fee24 * 100, fee=fee24, apr=0),
        s7d=Stat(volume=fee24 * 700, fee=fee24 * 7, apr=0),
        s30d=Stat(),
        drawdown24h=-5,
        volatility=vol,
        lp_auto=True,
        dynamic_fee=False,
        tag="",
    )


def pos(value: float) -> Position:
    return Position(
        id="p",
        chain_id=4663,
        pool_address="0xcur",
        protocol="uniswapv4",
        token0="USDG",
        token1="ETH",
        status="IN_RANGE",
        value=value,
        deposit=value,
        withdrawn=0,
        pnl=0,
        roi_pct=0,
        il=0,
        fee_pending=0,
        fee_claimed=0,
        reward_pending=0,
        fee_apr=0,
        total_apr=0,
        min_price=1,
        max_price=2,
        current_price=1.5,
        opened_ts=int(time.time() - 86400),
    )


def test_rotation_ranks_by_net_and_excludes_current():
    cur = pool("0xcur", "ETH", 10_000_000, 5_000, vol=2)
    hot = pool("0xhot", "AI", 500_000, 20_000, vol=25)
    meh = pool("0xmeh", "SPY", 2_000_000, 1_000, vol=1)
    r = plan(
        pos(5_000),
        realised_fee_day=5.0,
        pools=[cur, hot, meh],
        profile=PROFILES["degen"],
        quote="USDG",
        current_pool=cur,
    )
    assert [c.pool.address for c in r.candidates] == ["0xhot", "0xmeh"]
    best = r.best
    assert best.uplift_day > 0 and best.payback_days is not None and best.payback_days < 1
    assert r.verdict.startswith("ROTATE")
    assert abs(r.cost - 15.0) < 1e-9


def test_stay_when_nothing_better():
    cur = pool("0xcur", "ETH", 100_000, 5_000, vol=2)
    dead = pool("0xdead", "X", 100_000, 300, vol=1)  # 30k vol: passes degen, earns little
    r = plan(
        pos(5_000),
        realised_fee_day=200.0,
        pools=[cur, dead],
        profile=PROFILES["degen"],
        quote=None,
        current_pool=cur,
    )
    assert r.best is not None and r.best.uplift_day < 0
    assert r.verdict.startswith("STAY")


def test_profile_filter_applies():
    cur = pool("0xcur", "ETH", 10_000_000, 5_000, vol=2)
    small = pool("0xsmall", "AI", 20_000, 5_000, vol=25)  # below balanced floor
    r = plan(pos(5_000), 5.0, [cur, small], PROFILES["balanced"], quote="USDG", current_pool=cur)
    assert r.candidates == [] and "no candidate" in r.verdict


def test_rotation_kind_matches_verdict():
    cur = pool("0xcur", "ETH", 10_000_000, 5_000, vol=2)
    hot = pool("0xhot", "AI", 500_000, 20_000, vol=25)
    r = plan(pos(10_000), 5.0, [cur, hot], PROFILES["degen"], quote="USDG", current_pool=cur)
    assert r.kind in {"rotate", "consider", "stay", "none"}
    assert r.verdict.lower().startswith(r.kind if r.kind != "none" else "no")
    empty = plan(pos(10_000), 5.0, [cur], PROFILES["degen"], quote="USDG", current_pool=cur)
    assert empty.kind == "none"


def test_rotation_rows_are_json_ready():
    from krystal_curator.vaults import Vault
    from krystal_curator.web_rotation import rotation_rows

    cur = pool("0xcur", "ETH", 10_000_000, 5_000, vol=2)
    hot = pool("0xhot", "AI", 500_000, 20_000, vol=25)
    closed = pos(10_000)
    closed.status = "CLOSED"
    vault = Vault(
        chain_id=4663,
        address="0xv",
        name="V",
        vault_type="autofarm",
        owned=True,
        tvl=1,
        pnl=0,
        apr=0,
        fee_generated=0,
        earning_24h=0,
        earning_30d=0,
        risk="",
        age_days=1,
        my_value=1,
        my_deposit=1,
        my_withdrawn=0,
        positions=[pos(10_000), closed],
    )
    rows = rotation_rows([vault], [cur, hot], PROFILES["degen"], quote="USDG")
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "p"
    assert row["current"]["grade"] and row["current"]["sigmaKnown"]
    assert row["best"]["pair"] == "USDG/AI"
    assert row["candidates"][0]["poolId"] == "4663:uniswapv4:0xhot"
    assert row["edge"]["name"] in {"lower", "upper"}
    assert row["kind"] == ("rotate" if row["best"]["paybackDays"] <= 3 else row["kind"])
