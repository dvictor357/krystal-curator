import json
import time
from pathlib import Path

from krystal_curator.bot import Bot
from krystal_curator.config import Config
from krystal_curator.models import Pool
from krystal_curator.monitor import Monitor
from krystal_curator.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "top_pools_robinhood.json"


class FakeTG:
    chat_id = "42"

    def __init__(self):
        self.sent: list[str] = []
        self.files: list[str] = []

    def set_commands(self, commands):
        return True

    def send(self, text, *, html=False):
        self.sent.append(text)
        return True

    def send_file(self, path, caption=""):
        self.files.append(str(path))
        return True

    def get_updates(self, offset, timeout=0):
        return []


def make_bot(tmp_path, monkeypatch):
    pools = [Pool.from_public(x) for x in json.loads(FIXTURE.read_text())["result"]]
    store = Store(tmp_path / "t.sqlite3")
    mon = Monitor(store, pools=pools)
    cfg = Config()
    from krystal_curator import bot as bot_mod

    monkeypatch.setattr(bot_mod.TokenMeta, "fetch", lambda self, c, a: {})
    monkeypatch.setattr(bot_mod.FlowCache, "fetch", lambda self, c, a: {})
    monkeypatch.setattr(
        bot_mod.TokenMeta, "__init__", lambda self, cache_dir=None: setattr(self, "_meta", {})
    )
    return Bot(FakeTG(), store, cfg, mon), store


def test_help_scan_pool(tmp_path, monkeypatch):
    bot, _ = make_bot(tmp_path, monkeypatch)
    assert "/scan" in bot.handle("/help")
    out = bot.handle("/scan aggressive 5")
    assert "AGGRESSIVE" in out and out.count("\n") >= 5
    out = bot.handle("/pool PONS")
    assert "PONS/USDG" in out and "open on Krystal" in out
    assert "no such pool" in bot.handle("/pool ZZZZZZ")
    assert "unknown command" in bot.handle("/nope")


def test_state_persists(tmp_path, monkeypatch):
    bot, store = make_bot(tmp_path, monkeypatch)
    assert "degen" in bot.handle("/profile degen")
    assert "$20,000" in bot.handle("/size 20k")
    bot.handle("/mute 1")
    assert bot.muted
    st = store.kv_get("bot.state")
    assert st["profile"] == "degen" and st["size"] == 20000 and st["muted_until"] > time.time()
    bot.handle("/unmute")
    assert not bot.muted


def test_watchlist(tmp_path, monkeypatch):
    bot, _ = make_bot(tmp_path, monkeypatch)
    assert "empty" in bot.handle("/watchlist")
    assert "watching PONS/USDG" in bot.handle("/watch PONS")
    assert "PONS/USDG" in bot.handle("/watchlist")
    assert "unwatched" in bot.handle("/unwatch PONS")


def test_ignores_other_chats(tmp_path, monkeypatch):
    bot, _ = make_bot(tmp_path, monkeypatch)
    bot.tg.get_updates = lambda offset, timeout=0: [
        {"update_id": 1, "message": {"chat": {"id": 999}, "text": "/help"}},
        {"update_id": 2, "message": {"chat": {"id": 42}, "text": "/status"}},
    ]
    bot.poll()
    assert len(bot.tg.sent) == 1 and "heartbeat" in bot.tg.sent[0]
    assert bot.offset == 3
