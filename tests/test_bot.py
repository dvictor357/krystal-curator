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

    def send(self, text, *, html=False, reply_markup=None):
        self.sent.append(text)
        self.markups = getattr(self, "markups", []) + [reply_markup]
        return True

    def answer_callback(self, cid, text=""):
        pass

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
    text, kb = bot.handle("/help")
    assert "/scan" in text and "keyboard" in kb
    out, kb = bot.handle("/scan aggressive 5")
    assert "AGGRESSIVE" in out and out.count("\n") >= 5
    assert kb and any(
        "/pool 0x" in b["callback_data"] for row in kb["inline_keyboard"] for b in row
    )
    out, kb = bot.handle("/pool PONS")
    assert "PONS/USDG" in out and "open on Krystal" in out
    assert any(b["text"].startswith("★") for row in kb["inline_keyboard"] for b in row)
    assert "no such pool" in bot.handle("/pool ZZZZZZ")[0]
    assert "unknown command" in bot.handle("/nope")[0]
    text, kb = bot.handle("/profile")
    assert kb and len(kb["inline_keyboard"][0]) == 4


def test_state_persists(tmp_path, monkeypatch):
    bot, store = make_bot(tmp_path, monkeypatch)
    assert "degen" in bot.handle("/profile degen")[0]
    assert "$20,000" in bot.handle("/size 20k")[0]
    bot.handle("/mute 1")
    assert bot.muted
    st = store.kv_get("bot.state")
    assert st["profile"] == "degen" and st["size"] == 20000 and st["muted_until"] > time.time()
    bot.handle("/unmute")
    assert not bot.muted


def test_watchlist(tmp_path, monkeypatch):
    bot, _ = make_bot(tmp_path, monkeypatch)
    assert "empty" in bot.handle("/watchlist")[0]
    assert "watching PONS/USDG" in bot.handle("/watch PONS")[0]
    assert "PONS/USDG" in bot.handle("/watchlist")[0]
    assert "unwatched" in bot.handle("/unwatch PONS")[0]


def test_ignores_other_chats(tmp_path, monkeypatch):
    bot, _ = make_bot(tmp_path, monkeypatch)
    bot.tg.get_updates = lambda offset, timeout=0: [
        {"update_id": 1, "message": {"chat": {"id": 999}, "text": "/help"}},
        {"update_id": 2, "message": {"chat": {"id": 42}, "text": "/status"}},
        {"update_id": 3, "message": {"chat": {"id": 42}, "text": "ℹ️ Status"}},  # menu button
        {
            "update_id": 4,
            "callback_query": {"id": "c", "data": "/size", "message": {"chat": {"id": 42}}},
        },
    ]
    bot.poll()
    assert len(bot.tg.sent) == 3
    assert "heartbeat" in bot.tg.sent[0] and "heartbeat" in bot.tg.sent[1]
    assert "size" in bot.tg.sent[2] and bot.tg.markups[2]["inline_keyboard"]
    assert bot.offset == 5
