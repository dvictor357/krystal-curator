"""Verdict log: dedupe rules, streaks, and the honesty check against realised fees."""

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("tortoise")

from tortoise import Tortoise

from krystal_curator import web_verdicts
from krystal_curator.web_db import User, Verdict


def row(kind="rotate", best="4663:uniswapv4:0xhot", fees=10.0, net=1.0, uplift=5.0):
    return {
        "id": "p1",
        "pair": "USDG/ETH",
        "kind": kind,
        "value": 1000.0,
        "cost": 3.0,
        "best": (
            {"pair": "USDG/AI", "poolId": best, "upliftDay": uplift, "paybackDays": 0.6}
            if best
            else None
        ),
        "current": {"netDay": net, "feesTotal": fees, "ageDays": 3.0},
    }


@pytest.fixture
async def db():
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["krystal_curator.web_db"]})
    await Tortoise.generate_schemas()
    yield await User.create(address="0x" + "1" * 40)
    await Tortoise.close_connections()


async def test_log_dedupes_until_change_or_six_hours(db):
    user = db
    await web_verdicts.log_rows(user, [row()])
    await web_verdicts.log_rows(user, [row()])
    assert await Verdict.all().count() == 1
    await web_verdicts.log_rows(user, [row(kind="stay")])
    assert await Verdict.all().count() == 2
    await web_verdicts.log_rows(user, [row(kind="stay", best="4663:uniswapv4:0xother")])
    assert await Verdict.all().count() == 3
    old = await Verdict.all().order_by("-at").first()
    old.at = datetime.now(UTC) - timedelta(hours=7)
    await old.save()
    await web_verdicts.log_rows(user, [row(kind="stay", best="4663:uniswapv4:0xother")])
    assert await Verdict.all().count() == 4
    await web_verdicts.log_rows(user, [])
    assert await Verdict.all().count() == 4


def make(kind, best, at, fees=0.0, net=1.0, uplift=5.0):
    return Verdict(
        position_id="p1",
        pair="USDG/ETH",
        kind=kind,
        best_pool="USDG/AI",
        best_pool_id=best,
        uplift_day=uplift,
        value=1000,
        current_net_day=net,
        fees_total=fees,
        age_days=1,
        at=at,
    )


def test_history_streak_previous_and_outcome():
    now = datetime(2026, 9, 19, tzinfo=UTC)
    hot = "4663:uniswapv4:0xhot"
    verdicts = [  # newest first
        make("rotate", hot, now - timedelta(hours=1)),
        make("rotate", hot, now - timedelta(hours=8)),
        make("rotate", hot, now - timedelta(days=2), fees=4.0, net=1.0, uplift=5.0),
        make("stay", "", now - timedelta(days=3), fees=1.0),
        make("stay", "", now - timedelta(days=20)),  # outside the outcome window
    ]
    h = web_verdicts.history_for(row(fees=10.0), verdicts, now)
    assert h["since"] == (now - timedelta(days=2)).timestamp()
    assert h["count"] == 5
    assert h["previous"]["kind"] == "stay"
    # Oldest verdict inside [24 h, 14 d]: the "stay" from 3 days ago.
    assert h["outcome"]["kind"] == "stay"
    assert h["outcome"]["days"] == pytest.approx(3.0)
    assert h["outcome"]["realisedFeeDay"] == pytest.approx((10.0 - 1.0) / 3.0)
    assert web_verdicts.history_for(row(), [], now) is None
    young = [make("rotate", hot, now - timedelta(hours=2))]
    assert web_verdicts.history_for(row(), young, now)["outcome"] is None


async def test_attach_history_groups_per_position(db):
    user = db
    await web_verdicts.log_rows(user, [row()])
    rows = [row(), row() | {"id": "p2"}]
    await web_verdicts.attach_history(user, rows)
    assert rows[0]["history"]["count"] == 1
    assert rows[1]["history"] is None
