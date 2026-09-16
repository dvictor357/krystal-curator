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


def test_realised_sigma_recovers_known_daily_sigma():
    import math
    import random

    from krystal_curator.backtest import realised_sigma, sigma_check

    rng = random.Random(7)
    sigma_day = 0.05  # 5 %/day
    step = 900  # 15-min snapshots
    series, price, ts = [], 100.0, 0
    for _ in range(4 * 24 * 7):  # one week
        series.append((ts, price, 5.0))
        price *= math.exp(rng.gauss(0, sigma_day * math.sqrt(step / 86400)))
        ts += step
    row = realised_sigma(series)
    assert row is not None
    assert row.n == len(series) - 1 and row.span_h > 160
    assert abs(row.realised - 5.0) < 0.6  # sampling noise on 672 returns is ~3 %
    assert row.stale_frac == 0.0
    chk = sigma_check({"0xa:uniswapv4": series})
    assert chk.rows[0].key == "0xa:uniswapv4"
    assert 0.85 < chk.median_ratio < 1.15
    assert chk.verdict.startswith("reported σ looks daily")


def test_realised_sigma_needs_span_and_flags_stale_feed():
    from krystal_curator.backtest import realised_sigma, sigma_check

    short = [(i * 60, 100.0 + i, 5.0) for i in range(20)]  # 20 min only
    assert realised_sigma(short) is None
    flat = [(i * 3600, 100.0, 5.0) for i in range(30)]  # never moves
    row = realised_sigma(flat)
    assert row is not None and row.realised == 0.0 and row.stale_frac == 1.0
    # reported σ below the floor → skipped, not a ratio
    dead = [(i * 3600, 100.0 + (i % 2), 0.1) for i in range(30)]
    chk = sigma_check({"dead": dead})
    assert chk.rows == [] and chk.skipped == 1
    assert chk.verdict == "not enough priced history yet"


def test_sigma_verdict_names_weekly_scale():
    from krystal_curator.backtest import SigmaCheck, SigmaRow

    chk = SigmaCheck(rows=[SigmaRow("k", 50, 24, 0, 3.8, 10.0, 0.38)])
    assert "7-day" in chk.verdict
