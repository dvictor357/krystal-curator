from krystal_curator.advisor import advise, price_ladder
from krystal_curator.positions import Position


def mk(cur: float, lo: float = 2000, hi: float = 3000, age_days: float = 2.0) -> Position:
    import time

    return Position(
        id="x",
        chain_id=4663,
        pool_address="0x",
        protocol="uniswapv4",
        token0="ETH",
        token1="USDG",
        status="IN_RANGE",
        value=5000,
        deposit=5000,
        withdrawn=0,
        pnl=0,
        roi_pct=0,
        il=0,
        fee_pending=4,
        fee_claimed=6,
        reward_pending=0,
        fee_apr=0,
        total_apr=0,
        min_price=lo,
        max_price=hi,
        current_price=cur,
        opened_ts=int(time.time() - age_days * 86400),
    )


def test_edges_in_sigma_and_days():
    a = advise(mk(2100), sigma_daily_pct=2.5)  # lower edge 4.76% away ≈ 1.9σ ≈ 3.6d
    assert a.lower is not None and a.upper is not None
    assert abs(a.lower.dist_pct - 100 * 100 / 2100) < 1e-6
    assert 1.8 < a.lower.sigmas < 2.0 and 3.4 < a.lower.days < 3.8
    assert a.nearest is a.lower and a.lower.urgency == "watch"
    assert not a.alert
    assert abs(a.fee_per_day - 5.0) < 1e-3 and abs(a.fee_yield_day - 5.0 / 5000) < 1e-6


def test_alert_when_edge_within_half_sigma():
    a = advise(mk(2020), sigma_daily_pct=5.0)  # 0.99% away = 0.2σ
    assert a.alert and a.nearest.urgency == "CRITICAL"


def test_no_sigma_no_alert():
    a = advise(mk(2020), sigma_daily_pct=None)
    assert a.lower.sigmas is None and not a.alert and a.lower.urgency == "?"


def test_price_ladder():
    assert price_ladder(mk(2000), width=12).startswith("├●")
    assert price_ladder(mk(2999), width=12).endswith("●┤")
    assert price_ladder(mk(3500), width=12).endswith("●")
    assert price_ladder(mk(1500), width=12).startswith("●")
    assert price_ladder(mk(2449.5), width=12).count("●") == 1
