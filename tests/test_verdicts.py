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


def _row(kind="rotate", fees=10.0, net=1.0, uplift=5.0, cost=3.0):
    r = row(kind=kind, fees=fees, net=net, uplift=uplift)
    r["cost"] = cost
    r["current"] |= {"poolId": "4663:uniswapv4:0xcur", "poolFee24": 500.0, "poolTvl": 100_000.0}
    if r["best"]:
        r["best"] |= {"feeDay": 6.0, "ilDay": 0.5, "tvl": 50_000.0, "poolFee24": 900.0}
    return r


async def test_samples_once_per_hour_per_pool(db):
    from krystal_curator.web_db import PoolSample

    assert await web_verdicts.record_samples([_row()]) == 2
    assert await web_verdicts.record_samples([_row()]) == 0
    assert await PoolSample.all().count() == 2


def test_judge_needs_a_day_and_two_samples():
    from krystal_curator.web_db import PoolSample

    now = datetime(2026, 9, 19, tzinfo=UTC)
    hot = "4663:uniswapv4:0xhot"
    v = make("rotate", hot, now - timedelta(days=3), fees=4.0, net=1.0, uplift=5.0)
    v.best_fee_day, v.best_il_day, v.cost = 6.0, 0.5, 3.0
    assert web_verdicts.judge(v, None, [], now) is None
    young = make("rotate", hot, v.at + timedelta(hours=20), fees=6.0)
    assert web_verdicts.judge(v, young, [], now) is None  # under a day of evidence
    later = make("rotate", hot, now, fees=10.0)
    out = web_verdicts.judge(v, later, [], now)
    assert out["realisedFeeDay"] == pytest.approx(2.0) and out["alternative"] is None
    samples = [
        PoolSample(pool_id=hot, fee24=900.0, tvl=50_000.0, at=now - timedelta(days=2)),
        PoolSample(pool_id=hot, fee24=1100.0, tvl=50_000.0, at=now - timedelta(days=1)),
        PoolSample(pool_id=hot, fee24=5000.0, tvl=50_000.0, at=now + timedelta(days=1)),  # after
    ]
    out = web_verdicts.judge(v, later, samples, now)
    alt = out["alternative"]
    assert alt["samples"] == 2
    share = 1000 / (50_000 + 1000)  # value 1000 into a 50k pool, mean fee24 1000
    assert alt["realisedFeeDay"] == pytest.approx(1000 * share)
    assert alt["realisedUpliftDay"] == pytest.approx(1000 * share - 2.0 - 3.0 / 3)
    assert alt["hit"] is True


async def test_track_record_aggregates_and_anonymises(db):
    user = db
    other = await User.create(address="0x" + "2" * 40)
    now = datetime.now(UTC)
    hot = "4663:uniswapv4:0xhot"
    for u, pos, at, fees in (
        (user, "p1", 3, 4.0),
        (user, "p1", 0, 10.0),
        (other, "p9", 2, 1.0),
        (other, "p9", 0, 5.0),
    ):
        v = make("rotate", hot, now - timedelta(days=at), fees=fees, net=1.0, uplift=5.0)
        v.user = u
        v.position_id = pos
        v.best_fee_day, v.best_il_day, v.cost = 6.0, 0.5, 3.0
        await v.save()
    from krystal_curator.web_db import PoolSample

    for d in (2.5, 1.5, 0.5):
        s = PoolSample(pool_id=hot, fee24=1000.0, tvl=50_000.0)
        await s.save()
        s.at = now - timedelta(days=d)
        await s.save()
    tr = await web_verdicts.track_record(30, now)
    assert tr["verdicts"]["total"] == 4 and tr["verdicts"]["rotate"] == 4
    assert tr["users"] == 2 and tr["positions"] == 2
    assert tr["judged"] == 2 and tr["rotate"]["n"] == 2
    assert tr["rotate"]["hitRate"] == 1.0
    assert tr["stay"]["medianRealisedFeeDay"] == pytest.approx(2.0)
    assert "0x" not in str(tr) and "p1" not in str(tr)
