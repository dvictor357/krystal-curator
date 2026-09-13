import math

from krystal_curator.models import Pool, Stat
from krystal_curator.position import il_fraction, simulate


def mk(tvl: float, fee24: float, vol: float) -> Pool:
    return Pool(
        chain_id=4663,
        protocol="uniswapv4",
        address="0x1",
        token0="USDG",
        token1="X",
        fee_tier_pct=0.3,
        tvl=tvl,
        s1h=Stat(),
        s24h=Stat(volume=fee24 * 100, fee=fee24, apr=0),
        s7d=Stat(volume=fee24 * 700, fee=fee24 * 7, apr=0),
        s30d=Stat(),
        drawdown24h=-1,
        volatility=vol,
        lp_auto=True,
        dynamic_fee=False,
        tag="",
    )


def test_il_fraction_known_values():
    assert il_fraction(1.0) == 0.0
    assert math.isclose(il_fraction(2.0), -0.0572, abs_tol=1e-3)  # classic 2x → -5.7%
    assert math.isclose(il_fraction(0.5), -0.0572, abs_tol=1e-3)


def test_dilution_and_share():
    s = simulate(mk(tvl=50_000, fee24=1_000, vol=10), size=50_000)
    assert math.isclose(s.share, 0.5)
    assert math.isclose(s.fee_day, 500)
    assert s.crowding == "YOU ARE THE POOL"
    s2 = simulate(mk(tvl=5_000_000, fee24=1_000, vol=10), size=50_000)
    assert s2.share < 0.01 and s2.crowding == "ok"
    assert s2.fee_day < s.fee_day


def test_il_and_net():
    s = simulate(mk(tvl=1_000_000, fee24=5_000, vol=20), size=50_000)
    assert math.isclose(s.il_day_pct, 0.2 * 0.2 / 8 * 100)  # 0.5 %/day
    assert math.isclose(s.il_day, 250)
    assert math.isclose(s.net_day, s.fee_day - 250)
    assert math.isclose(s.range_1s_7d, 20 * math.sqrt(7))
    assert s.breakeven_days is not None and s.breakeven_days > 0


def test_zero_vol_pool():
    s = simulate(mk(tvl=1_000_000, fee24=100, vol=0), size=50_000)
    assert s.il_day == 0 and s.fee_il_ratio == math.inf and s.net_day == s.fee_day
