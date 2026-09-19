"""RPC price decoding, orientation against the feed, and the alert-loop refresh."""

import time

import pytest

from krystal_curator import chain_rpc
from krystal_curator.models import Pool, Stat
from krystal_curator.positions import Position

Q96 = 2**96


def pool(addr, t0, t1, d0="0xaa", d1="0xbb"):
    return Pool(
        4663, "uniswapv3", addr, t0, t1, 0.3, 1e6, Stat(), Stat(), Stat(), Stat(),
        0, 0, True, False, "", token0_addr=d0, token1_addr=d1,
    )  # fmt: skip


def position(pool_address, price, lo, hi, status="IN_RANGE", alt=""):
    return Position(
        id=pool_address, chain_id=4663, pool_address=pool_address, protocol="uniswapv3",
        token0="A", token1="B", status=status, value=100, deposit=100, withdrawn=0, pnl=0,
        roi_pct=0, il=0, fee_pending=0, fee_claimed=0, reward_pending=0, fee_apr=0,
        total_apr=0, min_price=lo, max_price=hi, current_price=price,
        opened_ts=int(time.time()), pool_alt=alt,
    )  # fmt: skip


def test_orientation_picks_the_feeds_side_or_gives_up():
    assert chain_rpc.orient(2600.0, 2590.0) == 2600.0
    assert chain_rpc.orient(2600.0, 1 / 2590.0) == pytest.approx(1 / 2600.0)
    assert chain_rpc.orient(2600.0, 5.0) is None  # neither p nor 1/p is near the feed
    assert chain_rpc.orient(0.0, 2600.0) is None and chain_rpc.orient(2600.0, None) is None


def test_sqrt_price_to_human_units(monkeypatch):
    # sqrtPriceX96 for 2500 token1(6 dec) per token0(18 dec): raw = 2500e-12
    raw = 2500 * 10 ** (6 - 18)
    sqrt = int((raw**0.5) * Q96)
    calls = []

    def fake_calls(chain, items, timeout=20.0):
        calls.append(items)
        out = []
        for to, data in items:
            if data == chain_rpc.SLOT0:
                out.append("0x" + format(sqrt, "064x") + "00" * 32)
            elif data == chain_rpc.DECIMALS:
                out.append("0x" + format(18 if to == "0xaa" else 6, "064x"))
            elif data.startswith(chain_rpc.GET_SLOT0):
                out.append("0x" + format(sqrt, "064x"))
            else:
                out.append(None)
        return out

    monkeypatch.setattr(chain_rpc, "_calls", fake_calls)
    chain_rpc._decimals_cache.clear()
    v4 = pool(
        "0x" + "1" * 64, "ETH", "USDC", d0="0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", d1="0xbb"
    )
    prices = chain_rpc.pool_prices(
        4663, [pool("0xp", "ETH", "USDC"), v4, pool("0xq", "X", "Y", d0="0xzz", d1="0xzz")]
    )
    assert prices["0xp"] == pytest.approx(2500.0, rel=1e-6)
    assert prices[v4.address] == pytest.approx(2500.0, rel=1e-6)  # native side = 18 decimals
    # Decimals are cached: a second run makes no decimals calls.
    calls.clear()
    chain_rpc.pool_prices(4663, [pool("0xp", "ETH", "USDC")])
    assert all(d != chain_rpc.DECIMALS for items in calls for _, d in items)


def test_refresh_prices_sets_status_from_live_price(monkeypatch):
    monkeypatch.setattr(chain_rpc, "pool_prices", lambda chain, pools: {"0xp": 3000.0, "0xr": 0.5})
    positions = [
        position("0xp", 2600.0, 2200, 2700),  # live 3000 > hi → out of range
        position(
            "0xr", 2.0, 1, 3, alt="0xr"
        ),  # feed says 2.0; live 0.5 ⇒ 1/0.5 = 2.0 fits, stays in range
        position("0xnone", 1.0, 0.5, 2),  # pool unknown: untouched
        position("0xp", 2600.0, 2200, 2700, status="CLOSED"),
    ]
    n = chain_rpc.refresh_prices(
        4663, positions, [pool("0xp", "ETH", "USDC"), pool("0xr", "A", "B")]
    )
    assert n == 2
    assert positions[0].status == "OUT_RANGE" and positions[0].current_price == 3000.0
    assert positions[1].status == "IN_RANGE" and positions[1].current_price == pytest.approx(2.0)
    assert positions[2].current_price == 1.0 and positions[3].status == "CLOSED"
