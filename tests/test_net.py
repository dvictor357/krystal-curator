"""Shared HTTP door: retries with backoff, and no secret survives into any error text."""

from __future__ import annotations

import logging
import random

import httpx
import pytest

from krystal_curator import net
from krystal_curator.notify import Telegram

TOKEN = "123456789:AAH-abcdefghijklmnopqrstuvwxyz012345"
KEY = "kc_supersecretkey_0123456789"


@pytest.fixture(autouse=True)
def _clean_secrets():
    saved = set(net._SECRETS)
    net._SECRETS.clear()
    yield
    net._SECRETS.clear()
    net._SECRETS.update(saved)


def _client(script):
    """MockTransport that replays `script`: each item is a status int or an exception."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = script[min(len(calls) - 1, len(script) - 1)]
        if isinstance(item, Exception):
            raise item
        status, headers = (item, {}) if isinstance(item, int) else item
        return httpx.Response(status, headers=headers, json={"ok": status == 200})

    c = httpx.Client(transport=httpx.MockTransport(handler))
    c.calls = calls  # type: ignore[attr-defined]
    return c


def _no_sleep():
    delays: list[float] = []
    return delays, delays.append


# ---- retries ------------------------------------------------------------


def test_retries_5xx_then_succeeds_with_backoff():
    c = _client([503, 500, 200])
    delays, sleep = _no_sleep()
    r = net.get("http://x/a", client=c, sleep=sleep, rng=random.Random(0), backoff=0.5)
    assert r.status_code == 200 and len(c.calls) == 3
    assert len(delays) == 2 and delays[0] < delays[1]  # exponential + jitter
    assert all(0.5 <= d <= net.MAX_BACKOFF_S + 0.5 for d in delays)


def test_honours_retry_after_and_caps_it():
    c = _client([(429, {"retry-after": "2"}), (503, {"retry-after": "999"}), 200])
    delays, sleep = _no_sleep()
    net.get("http://x/a", client=c, sleep=sleep)
    assert delays == [2.0, net.MAX_RETRY_AFTER_S]


def test_gives_up_after_retries_and_returns_last_response():
    c = _client([503])
    delays, sleep = _no_sleep()
    r = net.get("http://x/a", client=c, sleep=sleep, retries=2)
    assert r.status_code == 503 and len(c.calls) == 3 and len(delays) == 2
    err = net.status_error(r, "thing")
    assert str(err) == "thing: HTTP 503 from http://x/a" and err.status == 503


def test_transport_errors_retry_then_raise_http_error():
    c = _client([httpx.ConnectError("boom"), httpx.ReadTimeout("slow"), 200])
    _, sleep = _no_sleep()
    assert net.get("http://x/a", client=c, sleep=sleep).status_code == 200
    c2 = _client([httpx.ConnectError("boom")])
    with pytest.raises(net.HttpError, match=r"GET http://x/a: ConnectError: boom") as ei:
        net.get("http://x/a", client=c2, sleep=sleep, retries=1)
    assert ei.value.__cause__ is None  # nothing unredacted hangs off the exception


def test_post_retries_only_when_request_never_reached_server():
    _, sleep = _no_sleep()
    c = _client([httpx.ConnectError("down"), 200])
    assert net.post("http://x/a", client=c, sleep=sleep).status_code == 200
    c2 = _client([httpx.ReadTimeout("ambiguous"), 200])
    with pytest.raises(net.HttpError, match="ReadTimeout"):
        net.post("http://x/a", client=c2, sleep=sleep)
    assert len(c2.calls) == 1  # a duplicate alert is worse than a lost one
    c3 = _client([503, 200])
    assert net.post("http://x/a", client=c3, sleep=sleep).status_code == 200  # server said retry


def test_non_retry_status_returns_immediately():
    c = _client([404])
    delays, sleep = _no_sleep()
    assert net.get("http://x/a", client=c, sleep=sleep).status_code == 404
    assert len(c.calls) == 1 and not delays
    c2 = _client([503, 200])
    assert net.get("http://x/a", client=c2, sleep=sleep, retry_statuses=()).status_code == 503


# ---- redaction ----------------------------------------------------------


def test_redact_registered_secrets_and_token_shapes():
    net.register_secret(KEY)
    net.register_secret("short")  # too short to be safe to scrub
    assert net.redact(f"key {KEY} used") == "key <redacted> used"
    assert net.redact("short story") == "short story"
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert net.redact(url) == "https://api.telegram.org/bot<redacted>/sendMessage"  # unregistered


def test_errors_and_logs_never_carry_the_token(caplog):
    caplog.set_level(logging.WARNING)
    tg = Telegram(TOKEN, "42")
    c = _client([httpx.ConnectError(f"cannot reach https://api.telegram.org/bot{TOKEN}/x")])
    _, sleep = _no_sleep()
    with pytest.raises(net.HttpError) as ei:
        net.post(f"{tg.base}/sendMessage", client=c, sleep=sleep, retries=1)
    assert TOKEN not in str(ei.value) and "<redacted>" in str(ei.value)
    assert TOKEN not in caplog.text and "retry 1/1" in caplog.text


def test_httpx_logger_is_filtered(caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    net.register_secret(KEY)
    logging.getLogger("httpx").info("HTTP Request: GET https://x/?k=%s", KEY)
    assert KEY not in caplog.text and "<redacted>" in caplog.text


def test_telegram_send_failure_is_logged_redacted(caplog, monkeypatch):
    caplog.set_level(logging.WARNING)
    tg = Telegram(TOKEN, "42")
    monkeypatch.setattr(net, "post", lambda url, **kw: httpx.Response(401, text=f"bad {url}"))
    assert tg.send("hi") is False
    assert "telegram sendMessage: HTTP 401" in caplog.text and TOKEN not in caplog.text
