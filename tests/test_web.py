"""Web contracts and optional real PostgreSQL account-isolation integration check."""

import asyncio
import hashlib
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("tortoise")

from tortoise import Tortoise

from krystal_curator.models import Pool, Stat
from krystal_curator.web_api import app, pool_rows
from krystal_curator.web_auth import throttle
from krystal_curator.web_db import RateLimit, Session, User


def test_unknown_volatility_is_not_zero_risk():
    pool = Pool(
        4663,
        "uniswapv3",
        "0x" + "a" * 40,
        "USDG",
        "TEST",
        0.3,
        500_000,
        Stat(10000, 30),
        Stat(300000, 900),
        Stat(2100000, 6300),
        Stat(9000000, 27000),
        0,
        0,
        True,
        False,
        "",
        unknown=frozenset({"volatility", "stat7d"}),
    )
    row = pool_rows([pool], "balanced", "USDG", 10000)[0]
    assert row["volatility"] is None
    assert row["sim"]["il_day"] is None
    assert row["sim"]["net_day"] is None
    assert row["sim"]["fee_day_7d"] is None
    assert row["sim"]["fee_day"] > 0
    assert "σ?" in row["flags"]
    assert row["token0"] == "USDG"
    assert row["token1"] == "TEST"
    assert row["feeTier"] == 0.3
    assert row["token0Logo"] == ""
    assert row["token1Logo"] == ""


async def test_postgres_accounts_isolated_and_sessions_revoked(monkeypatch):
    url = os.environ.get("CURATOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set CURATOR_TEST_DATABASE_URL to a migrated disposable PostgreSQL DB")
    if not url.rsplit("/", 1)[-1].startswith("curator_test"):
        pytest.fail("Integration tests require a dedicated curator_test* database")
    await Tortoise.init(db_url=url, modules={"models": ["krystal_curator.web_db", "aerich.models"]})
    monkeypatch.setenv("CURATOR_API_SECRET", "web-integration-test-secret-32-characters")
    monkeypatch.setenv("CURATOR_COOKIE_SECURE", "false")
    prefix = uuid.uuid4().hex
    headers = {
        "Authorization": "Bearer web-integration-test-secret-32-characters",
        "X-Curator-Client": prefix,
    }
    password = "a-long-test-passphrase-42"
    transport = httpx.ASGITransport(app=app)
    emails = [f"{prefix}-{i}@example.com" for i in range(2)]
    pool_id = "4663:uniswapv3:0x" + "a" * 40
    try:
        async with (
            httpx.AsyncClient(
                transport=transport, base_url="http://test", headers=headers
            ) as alice,
            httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as bob,
        ):
            assert (await alice.get("/account")).status_code == 401
            for client, email in zip((alice, bob), emails, strict=True):
                response = await client.post(
                    "/auth/register", json={"email": email, "password": password}
                )
                assert response.status_code == 201, response.text
                assert "HttpOnly" in response.headers["set-cookie"]
                assert "SameSite=lax" in response.headers["set-cookie"]
            token = alice.cookies.get("curator_session")
            assert await Session.filter(token_hash=token).count() == 0
            assert (
                await Session.filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).count()
                == 1
            )
            response = await alice.post(
                "/account", json={"action": "watch", "poolId": pool_id, "watched": True}
            )
            assert response.status_code == 200, response.text
            assert (await alice.get("/account")).json()["watchlist"] == [pool_id]
            assert (await bob.get("/account")).json()["watchlist"] == []
            prefs = {
                "profile": "degen",
                "chain": 4663,
                "source": "krystal",
                "size": 25000,
                "wallet": "",
            }
            assert (
                await alice.post("/account", json={"action": "settings", "settings": prefs})
            ).status_code == 200
            assert (await bob.get("/account")).json()["settings"] is None
            assert (await alice.get("/account")).json()["settings"]["size"] == 25000
            assert (
                await bob.post(
                    "/account", json={"action": "watch", "poolId": pool_id, "watched": False}
                )
            ).status_code == 200
            assert (await alice.get("/account")).json()["watchlist"] == [pool_id]
            assert (
                await bob.post(
                    "/account",
                    json={
                        "action": "watch",
                        "poolId": pool_id,
                        "watched": True,
                        "user_id": "forged",
                    },
                )
            ).status_code == 422
            assert (
                await alice.post(
                    "/account",
                    json={
                        "action": "settings",
                        "settings": prefs | {"source": "chain", "chain": 1},
                    },
                )
            ).status_code == 422
            assert (await alice.get("/pools?source=chain&chain=1")).status_code == 422
            assert (await alice.post("/auth/logout")).status_code == 200
            alice.cookies.set("curator_session", token)
            assert (await alice.get("/account")).status_code == 401
            assert (
                await alice.post(
                    "/auth/login", json={"email": emails[0], "password": "wrong-password-value"}
                )
            ).status_code == 401
            alice.cookies.clear()
            assert (
                await alice.post(
                    "/auth/login", json={"email": emails[0].upper(), "password": password}
                )
            ).status_code == 200
            assert (await alice.get("/account")).json()["watchlist"] == [pool_id]
            new_token = alice.cookies.get("curator_session")
            await Session.filter(token_hash=hashlib.sha256(new_token.encode()).hexdigest()).update(
                expires_at=datetime.now(UTC) - timedelta(seconds=1)
            )
            assert (await alice.get("/account")).status_code == 401
            assert (
                await bob.get("/account", headers={"Authorization": "Bearer wrong"})
            ).status_code == 401
            # The shared DB counter cannot be bypassed by concurrent API workers.
            results = await asyncio.gather(
                *(throttle(f"test:{prefix}", 3) for _ in range(6)), return_exceptions=True
            )
            assert sum(result is None for result in results) == 3
    finally:
        users = await User.filter(email__in=emails).values_list("id", flat=True)
        for user_id in users:
            await RateLimit.filter(key__in=[f"account:{user_id}", f"market:{user_id}"]).delete()
        await User.filter(email__in=emails).delete()
        keys = ["test:" + prefix, "auth-ip:" + hashlib.sha256(prefix.encode()).hexdigest()]
        keys += ["auth-email:" + hashlib.sha256(email.encode()).hexdigest() for email in emails]
        await RateLimit.filter(key__in=keys).delete()
        await Tortoise.close_connections()


def test_cache_serves_stale_and_refreshes_in_background(monkeypatch):
    import threading

    from krystal_curator import web_api

    cache = web_api.Cache()
    calls = []
    done = threading.Event()

    def fetch():
        calls.append(1)
        if len(calls) == 2:
            done.set()
        return len(calls)

    entry, meta = cache.get(("k",), fetch, ttl=10, stale=100)
    assert (entry.value, meta.cache) == (1, "miss")
    assert meta.upstream_ms >= 0
    entry, meta = cache.get(("k",), fetch, ttl=10, stale=100)
    assert (entry.value, meta.cache) == (1, "hit")
    # Past ttl but inside the stale window: old value now, refresh in the background.
    cache.entries[("k",)].at -= 11
    entry, meta = cache.get(("k",), fetch, ttl=10, stale=100)
    assert (entry.value, meta.cache) == (1, "stale")
    assert done.wait(2)
    for _ in range(50):
        if ("k",) not in cache.refreshing:
            break
        time.sleep(0.01)
    entry, meta = cache.get(("k",), fetch, ttl=10, stale=100)
    assert (entry.value, meta.cache) == (2, "hit")
    # Manual refresh bypasses a fresh entry; upstream failure keeps the stale copy.
    entry, meta = cache.get(("k",), fetch, ttl=10, stale=100, fresh=True)
    assert (entry.value, meta.cache) == (3, "miss")

    def broken():
        raise web_api.api.KrystalError("down")

    cache.entries[("k",)].at -= 11
    entry, meta = cache.get(("k",), broken, ttl=10, stale=100)
    assert (entry.value, meta.cache) == (3, "stale")
    for _ in range(50):
        if ("k",) not in cache.refreshing:
            break
        time.sleep(0.01)
    assert cache.entries[("k",)].value == 3
    cache.entries[("k",)].at -= 1000
    with pytest.raises(web_api.HTTPException):
        cache.get(("k",), broken, ttl=10, stale=100)


def test_cache_one_upstream_call_per_key_under_concurrency():
    import threading

    from krystal_curator import web_api

    cache = web_api.Cache()
    calls = []
    gate = threading.Event()

    def slow():
        calls.append(1)
        gate.wait(2)
        return "v"

    results = []
    workers = [
        threading.Thread(target=lambda: results.append(cache.get(("k",), slow)[1].cache))
        for _ in range(5)
    ]
    for w in workers:
        w.start()
    time.sleep(0.1)
    gate.set()
    for w in workers:
        w.join(3)
    assert len(calls) == 1
    assert sorted(results) == ["hit"] * 4 + ["miss"]


def test_quote_resolution_per_chain():
    from krystal_curator import web_api

    assert web_api.quote_for(4663, "") == "USDG"
    assert web_api.quote_for(8453, "") == "USDC"
    assert web_api.quote_for(1, "") == "WETH"
    assert web_api.quote_for(4663, "any") is None
    assert web_api.quote_for(42161, "USD₮0") == "USD₮0"
