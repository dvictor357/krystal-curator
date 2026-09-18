"""Alert loop: rules across ticks, the job lease, and one full tick with a stubbed bot."""

import time
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("tortoise")

from tortoise import Tortoise

from krystal_curator import web_alerts
from krystal_curator.models import Pool, Stat
from krystal_curator.positions import Position
from krystal_curator.vaults import Vault
from krystal_curator.web_cache import Cache
from krystal_curator.web_db import AlertState, Job, Preferences, User


def pool(addr, sym, tvl, fee24, vol=10.0):
    return Pool(
        4663, "uniswapv4", addr, "USDG", sym, 0.3, tvl,
        Stat(fee24 * 4, fee24 / 24, 0), Stat(fee24 * 100, fee24, 0),
        Stat(fee24 * 700, fee24 * 7, 0), Stat(), -5, vol, True, False, "",
    )  # fmt: skip


def position(status="IN_RANGE", price=1.5, pnl=0.0):
    return Position(
        id="p1", chain_id=4663, pool_address="0xcur", protocol="uniswapv4",
        token0="USDG", token1="ETH", status=status, value=10_000, deposit=10_000,
        withdrawn=0, pnl=pnl, roi_pct=0, il=0, fee_pending=1, fee_claimed=0,
        reward_pending=0, fee_apr=0, total_apr=0, min_price=1, max_price=2,
        current_price=price, opened_ts=int(time.time() - 86400), vault="V",
    )  # fmt: skip


def vault(pos):
    return Vault(
        4663, "0xv", "V", "autofarm", True, 1, 0, 0, 0, 0, 0, "", 1, 1, 1, 0, positions=[pos]
    )


def prefs(**kw):
    return Preferences(profile="degen", chain=4663, source="krystal", size=10000, **kw)


def test_rules_fire_on_change_not_on_first_sight():
    cur = pool("0xcur", "ETH", 10_000_000, 5_000, vol=2)
    hot = pool("0xhot", "AI", 500_000, 20_000, vol=25)
    quiet = pool("0xquiet", "SPY", 50_000_000, 10, vol=1)
    # First tick: rotate verdict exists but is not announced; only bad current state is.
    alerts, state = web_alerts.evaluate(prefs(), [vault(position())], [cur, hot], {})
    assert [a.title for a in alerts] == []
    assert state["p1"]["kind"] == "rotate"
    # Nothing changed: silence.
    alerts, state = web_alerts.evaluate(prefs(), [vault(position())], [cur, hot], state)
    assert alerts == []
    # Rotation window closes when the hot pool leaves the feed.
    alerts, state = web_alerts.evaluate(prefs(), [vault(position())], [cur, quiet], state)
    assert [a.title for a in alerts] == ["ROTATE"]
    assert "closed" in alerts[0].text
    # Reopens → ROTATE alert; goes out of range → POSITION alert.
    alerts, state = web_alerts.evaluate(
        prefs(), [vault(position(status="OUT_RANGE", price=3))], [cur, hot], state
    )
    titles = [a.title for a in alerts]
    assert "ROTATE" in titles and "POSITION" in titles
    # First sight of an out-of-range position is reported even with no history.
    alerts, _ = web_alerts.evaluate(
        prefs(), [vault(position(status="OUT_RANGE", price=3))], [cur], {}
    )
    assert [a.title for a in alerts] == ["POSITION"]


def test_message_is_html_safe():
    text = web_alerts.format_message(
        [web_alerts.Alert("ROTATE", "USDG/ETH: ROTATE → <AI>: +5$/d", "warning")]
    )
    assert "&lt;AI&gt;" in text and "<b>ROTATE</b>" in text


@pytest.fixture
async def db():
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["krystal_curator.web_db"]})
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


async def test_job_lease_is_exclusive(db):
    assert await web_alerts.claim("t", 60)
    assert not await web_alerts.claim("t", 60)
    job = await Job.get(name="t")
    job.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    await job.save()
    assert await web_alerts.claim("t", 60)


async def test_tick_sends_once_per_change_and_stores_state(db, monkeypatch):
    user = await User.create(address="0x" + "a" * 40)
    await Preferences.create(
        user=user, profile="degen", wallet="0x" + "b" * 40, telegram_chat_id="42"
    )
    await Preferences.create(
        user=await User.create(address="0x" + "c" * 40), wallet="0x" + "d" * 40
    )
    cur = pool("0xcur", "ETH", 10_000_000, 5_000, vol=2)
    hot = pool("0xhot", "AI", 500_000, 20_000, vol=25)
    feed = {"pos": vault(position()), "pools": [cur, hot]}
    monkeypatch.setattr(web_alerts.vaults, "fetch_vaults", lambda w, chain_id: [feed["pos"]])
    monkeypatch.setattr(web_alerts.api, "fetch_pools", lambda chain, source: feed["pools"])
    sent = []

    class Bot:
        def __init__(self, token, chat_id):
            self.chat_id = chat_id

        def send(self, text, html=False, **kw):
            sent.append((self.chat_id, text))
            return True

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(web_alerts.notify, "Telegram", Bot)
    cache = Cache()
    assert await web_alerts.tick(cache) == 0  # first sight, in range: quiet
    assert (await AlertState.get(user=user, position_id="p1")).state["kind"] == "rotate"
    feed["pos"] = vault(position(status="OUT_RANGE", price=3))
    cache.entries.clear()
    assert await web_alerts.tick(cache) == 1
    assert sent[0][0] == "42" and "OUT OF RANGE" in sent[0][1]
    cache.entries.clear()
    assert await web_alerts.tick(cache) == 0  # unchanged: no repeat
    # Position gone from the feed → state row removed.
    monkeypatch.setattr(web_alerts.vaults, "fetch_vaults", lambda w, chain_id: [])
    cache.entries.clear()
    await web_alerts.tick(cache)
    assert await AlertState.filter(user=user).count() == 0
