import time

from krystal_curator.analytics import idle_capital, real_roi, report_markdown, track_record
from krystal_curator.positions import Position
from krystal_curator.vaults import Vault


def closed(
    pair: str, pnl: float, fees: float, days: float, proto="uniswapv4", tier=0.3
) -> Position:
    return Position(
        id=f"{pair}{pnl}",
        chain_id=4663,
        pool_address="0x",
        protocol=proto,
        token0=pair.split("/")[0],
        token1=pair.split("/")[1],
        status="CLOSED",
        value=0,
        deposit=1000,
        withdrawn=0,
        pnl=pnl,
        roi_pct=pnl / 10,
        il=0,
        fee_pending=0,
        fee_claimed=fees,
        reward_pending=0,
        fee_apr=0,
        total_apr=0,
        min_price=1,
        max_price=2,
        current_price=None,
        opened_ts=int(time.time() - days * 86400),
        vault="V",
        fee_tier=tier,
    )


def test_track_record():
    cs = [
        closed("A/USDG", 50, 20, 2),
        closed("A/USDG", -10, 5, 1),
        closed("B/USDG", 30, 30, 3, proto="ramsescl", tier=0.1),
    ]
    tr = track_record(cs)
    assert tr.n == 3 and tr.wins == 2 and abs(tr.win_rate - 2 / 3) < 1e-9
    assert abs(tr.pnl - 70) < 1e-9 and abs(tr.fees - 55) < 1e-9 and abs(tr.price_pnl - 15) < 1e-9
    assert abs(tr.median_pnl - 30) < 1e-9 and abs(tr.avg_hold_days - 2) < 1e-3
    assert tr.best.pnl == 50 and tr.worst.pnl == -10
    assert [b.key for b in tr.by_pair] == ["A/USDG", "B/USDG"]  # sorted by pnl desc
    assert tr.by_pair[0].n == 2 and abs(tr.by_pair[0].win_rate - 0.5) < 1e-9
    assert {b.key for b in tr.by_protocol} == {"uniswapv4", "ramsescl"}
    assert {b.key for b in tr.by_tier} == {"0.30%", "0.10%"}
    assert track_record([]).n == 0


def vault() -> Vault:
    v = Vault(
        chain_id=4663,
        address="0xv",
        name="Mr. Farmer",
        vault_type="autofarm",
        owned=True,
        tvl=6000,
        pnl=40,
        apr=3.5,
        fee_generated=120,
        earning_24h=30,
        earning_30d=887,
        risk="HIGH",
        age_days=9,
        my_value=6000,
        my_deposit=16566,
        my_withdrawn=11617,
    )
    v.positions = [closed("ETH/USDG", -100, 8, 2)]
    v.positions[0].status = "IN_RANGE"
    v.positions[0].value = 4880
    v.closed = [closed("PONS/USDG", 65, 20, 1.5), closed("AI/USDG", -20, 3, 0.5)]
    return v


def test_idle_and_roi():
    v = vault()
    idle, frac = idle_capital(v)
    assert abs(idle - 1120) < 1e-9 and abs(frac - 1120 / 6000) < 1e-9
    gain, roi = real_roi(v)
    assert abs(gain - 1051) < 1e-9 and roi is not None and abs(roi - 1051 / 16566) < 1e-9


def test_report_markdown():
    md = report_markdown([vault()], chain="robinhood", equity={"0xv": [5000, 6000]})
    assert "# Vault report — robinhood" in md
    assert "## Mr. Farmer" in md and "idle 1,120$ (18.7%)" in md
    assert "| ETH/USDG |" in md and "| PONS/USDG | 1 | 100% |" in md
    assert "win rate **50%**" in md and "TVL trend (2 samples): 5,000$ → 6,000$ (+20.0%)" in md
