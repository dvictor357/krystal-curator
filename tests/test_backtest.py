import time

from krystal_curator.backtest import evaluate, spearman
from krystal_curator.profiles import PROFILES


def test_spearman_basic():
    assert abs(spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-9
    assert abs(spearman([1, 2, 3, 4], [40, 30, 20, 10]) + 1.0) < 1e-9
    assert spearman([1, 2], [1, 2]) is None


def rows_for(n_pools: int, hours: list[int]):
    """Synthetic universe where high-fee pools stay high-fee (score should predict)."""
    now = int(time.time())
    out = []
    for h in hours:
        ts = now - h * 3600
        for i in range(n_pools):
            tvl = 1_000_000
            fee24 = 200 * (i + 1)  # pool i earns proportionally more, persistently
            vol24 = fee24 * 300
            out.append(
                (
                    ts,
                    4663,
                    f"0x{i:02d}",
                    "uniswapv4",
                    tvl,
                    vol24,
                    fee24,
                    vol24 / 24,
                    fee24 / 24,
                    fee24 * 7,
                    0.0,
                    5.0,
                    -2.0,
                )
            )
    return out


def test_evaluate_finds_predictive_score():
    rows = rows_for(30, hours=[48, 24, 0])
    r = evaluate(rows, PROFILES["degen"], horizon_h=24)
    assert r.times == 2 and r.pairs == 60
    assert r.spearman is not None and r.spearman > 0.9
    assert len(r.decile_yield) == 10 and r.decile_yield[0] > r.decile_yield[-1]
    assert r.steady_next_yield is not None


def test_evaluate_insufficient():
    r = evaluate(rows_for(3, hours=[0]), PROFILES["degen"])
    assert r.pairs == 0 and r.spearman is None
