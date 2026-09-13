from krystal_curator.models import Pool, Stat
from krystal_curator.profiles import PROFILES
from krystal_curator.scoring import curate, passes, risk_grade, score_pool


def mk(**kw) -> Pool:
    base = {
        "chain_id": 4663,
        "protocol": "uniswapv4",
        "address": "0xabc",
        "token0": "USDG",
        "token1": "XYZ",
        "fee_tier_pct": 0.35,
        "tvl": 500_000,
        "s1h": Stat(volume=50_000, fee=175, apr=0),
        "s24h": Stat(volume=1_200_000, fee=4_200, apr=300),
        "s7d": Stat(volume=8_000_000, fee=28_000, apr=290),
        "s30d": Stat(volume=30_000_000, fee=105_000, apr=250),
        "drawdown24h": -8.0,
        "volatility": 12.0,
        "lp_auto": True,
        "dynamic_fee": False,
        "tag": "",
    }
    base.update(kw)
    return Pool(**base)


def test_fee_tier_is_percent_not_bps():
    p = Pool.from_public({"feeTier": 0.35, "chainId": 4663, "tvlUsd": "1"})
    assert p.fee_tier_pct == 0.35


def test_derived_metrics():
    p = mk()
    assert abs(p.fee_yield_24h - 4_200 / 500_000) < 1e-12
    assert abs(p.fee_yield_7d_daily - 4_000 / 500_000) < 1e-12
    assert abs(p.turnover_24h - 2.4) < 1e-9
    assert abs(p.consistency - 1.05) < 1e-9
    assert abs(p.liveness - 1.0) < 1e-9
    assert not p.is_new


def test_new_pool_detected_when_windows_identical():
    st = Stat(volume=1_000_000, fee=5_000, apr=1000)
    p = mk(s24h=st, s7d=st, s30d=st)
    assert p.is_new
    assert abs(p.consistency - 7.0) < 1e-9
    assert passes(p, PROFILES["balanced"]) == "new pool (<1d history)"
    assert passes(p, PROFILES["degen"]) is None


def test_hard_filters():
    assert passes(mk(tvl=100), PROFILES["conservative"]).startswith("tvl")
    assert passes(mk(volatility=99), PROFILES["balanced"]).startswith("volatility")
    assert passes(mk(lp_auto=False), PROFILES["aggressive"]) == "no LP auto support"
    assert passes(mk(), PROFILES["balanced"]) is None


def test_spike_scores_below_steady():
    steady = mk()
    spike = mk(s24h=Stat(volume=1_200_000, fee=40_000, apr=3000))  # 10x a normal day
    prof = PROFILES["balanced"]
    assert (
        score_pool(spike, prof).parts["consistency"] < score_pool(steady, prof).parts["consistency"]
    )
    # min(24h, 7d) yield means the spike doesn't inflate yield either
    assert score_pool(spike, prof).parts["yield"] == score_pool(steady, prof).parts["yield"]


def test_grade_ordering():
    assert risk_grade(mk(tvl=5_000_000, volatility=2, drawdown24h=-1)) == "A"
    assert risk_grade(mk(tvl=20_000, volatility=80, drawdown24h=-60, fee_tier_pct=5)) == "E"


def test_curate_quote_and_protocol_filters():
    pools = [
        mk(),
        mk(token0="WETH", token1="ABC", address="0x2"),
        mk(protocol="ramsescl", address="0x3"),
    ]
    assert len(curate(pools, PROFILES["balanced"], quote="USDG")) == 2
    assert len(curate(pools, PROFILES["balanced"], quote=None)) == 3
    assert len(curate(pools, PROFILES["balanced"], protocols={"ramsescl"})) == 1
