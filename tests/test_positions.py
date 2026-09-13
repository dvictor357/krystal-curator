import time

from krystal_curator.positions import parse_position

SAMPLE = {
    "chain": {"name": "Ethereum", "id": 1},
    "pool": {
        "id": "0xc7bbec68d12a0d1830360f8ec58fa599ba1b0e9b",
        "poolAddress": "0xc7bBeC68d12a0d1830360F8Ec58fA599bA1b0e9b",
        "protocol": {"name": "Uniswap V3", "key": "uniswapv3"},
    },
    "id": "0xc364-1028436",
    "minPrice": 2582.49,
    "maxPrice": 2854.36,
    "currentPositionValue": 154411.93,
    "status": "IN_RANGE",
    "currentAmounts": [
        {"token": {"symbol": "WETH"}, "price": 2785.92, "value": 40977.09},
        {"token": {"symbol": "USDT"}, "price": 1, "value": 112795.12},
    ],
    "providedAmounts": [],
    "tradingFee": {
        "pending": [
            {"token": {"symbol": "WETH"}, "value": 319.37},
            {"token": {"symbol": "USDT"}, "value": 100},
        ],
        "claimed": [{"token": {"symbol": "USDT"}, "value": 50}],
    },
    "farmingReward": {"pending": [], "claimed": []},
    "openedTime": int(time.time()) - 3 * 86400,
    "performance": {
        "totalDepositValue": 154091.08,
        "totalWithdrawValue": 0,
        "impermanentLoss": -120.5,
        "pnl": 640.2,
        "returnOnInvestment": 0.42,
        "apr": {"totalApr": 31.2, "feeApr": 31.2, "farmApr": 0},
    },
}


def test_parse_position_sample():
    p = parse_position(SAMPLE)
    assert p.pair == "WETH/USDT"
    assert p.protocol == "uniswapv3"
    assert p.pool_address == "0xc7bbec68d12a0d1830360f8ec58fa599ba1b0e9b"
    assert p.in_range
    assert abs(p.fee_pending - 419.37) < 1e-6
    assert abs(p.fee_claimed - 50) < 1e-6
    assert abs(p.fees_total - 469.37) < 1e-6
    assert abs(p.pnl - 640.2) < 1e-9
    assert 2.9 < p.age_days < 3.1
    assert p.current_price is not None and abs(p.current_price - 2785.92) < 1e-6
    rp = p.range_pos
    assert rp is not None and 0.7 < rp < 0.8  # 2785 sits near the top of 2582-2854
    assert 4 < p.range_width_pct < 6


def test_parse_position_tolerates_missing_fields():
    p = parse_position({"id": "x"})
    assert p.pair == "?/?" and p.value == 0 and p.range_pos is None and p.age_days == 0
