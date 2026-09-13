import time

from krystal_curator.autoconfig import recommend
from krystal_curator.positions import Position
from krystal_curator.profiles import PROFILES


def pos() -> Position:
    return Position(
        id="x",
        chain_id=4663,
        pool_address="0x",
        protocol="uniswapv4",
        token0="ETH",
        token1="USDG",
        status="IN_RANGE",
        value=4880,
        deposit=5000,
        withdrawn=0,
        pnl=0,
        roi_pct=0,
        il=0,
        fee_pending=0,
        fee_claimed=0,
        reward_pending=0,
        fee_apr=0,
        total_apr=0,
        min_price=2322,
        max_price=2870,
        current_price=2493,
        opened_ts=int(time.time() - 86400),
    )


def test_balanced_eth():
    s = recommend(pos(), 2.4, PROFILES["balanced"])
    assert s.hold_days == 7 and 6.0 <= s.range_pct <= 7.0  # 2.4·√7 = 6.35 → 6.5
    labels = {f.label for f in s.fields}
    assert {"Time Buffer", "New Range", "Swap Slippage", "Gas Fee Ceiling", "Recurring"} <= labels
    rng = next(f for f in s.fields if f.label == "New Range")
    assert "−6.5%" in rng.value and "+6.5%" in rng.value
    ex = next(f for f in s.fields if f.label.startswith("Emergency Exit"))
    assert "15%" in ex.value
    sections = s.by_section()
    assert set(sections) == {"Rebalance", "Auto Compound", "Auto Harvest", "Auto Exit", "General"}


def test_degen_wide_sigma_no_exit():
    s = recommend(pos(), 60.0, PROFILES["degen"])
    assert s.range_pct == 60.0  # σ·√1
    swap = next(f for f in s.fields if f.label == "Swap Slippage")
    assert swap.value == "3%"  # capped
    ex = next(f for f in s.fields if f.section == "Auto Exit")
    assert ex.value == "off"


def test_unknown_sigma_falls_back():
    s = recommend(pos(), None, PROFILES["conservative"])
    assert s.sigma is None and s.range_pct > 0
