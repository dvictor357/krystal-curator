"""Browser-fed data: recipes, multi-round ingest, per-user scoping, and the 409 handshake."""

import json
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")

from tortoise import Tortoise

from krystal_curator import web_feed
from krystal_curator.web_api import app
from krystal_curator.web_cache import Cache
from krystal_curator.web_db import User

FIXTURE = Path(__file__).parent / "fixtures" / "top_pools_robinhood.json"
VAULTS = Path(__file__).parent / "fixtures" / "vault_list.json"
WALLET = "0x" + "a" * 40


def test_recipes_name_every_request():
    r = web_feed.recipe_pools(4663)
    assert r["kind"] == "pools" and r["steps"][0]["params"]["chainId"] == "4663"
    r = web_feed.recipe_positions(4663, WALLET)
    assert {s["name"] for s in r["steps"]} == set(web_feed.POSITION_QUERIES)
    assert all(WALLET in s["params"].values() for s in r["steps"])
    r = web_feed.recipe_leaderboard(4663, [2, 3])
    assert r["round"] == 2 and [s["params"]["page"] for s in r["steps"]] == ["2", "3"]
    r = web_feed.recipe_review(4663, "0x" + "b" * 40)
    assert {"detail", "settings", "plans", "perf_24h"} <= {s["name"] for s in r["steps"]}


def test_ingest_pools_and_leaderboard_rounds():
    cache = Cache()
    out = web_feed.ingest_pools(cache, 4663, {"pools": json.loads(FIXTURE.read_text())}, 12.0)
    assert out["done"] and out["count"] > 10
    assert cache.peek(("pools", 4663, "krystal")).upstream_ms == 12.0
    page1, page2 = json.loads(VAULTS.read_text())  # fixture: two pages, totalPage 2
    out = web_feed.ingest_leaderboard(cache, 4663, 1, {"page_1": page1}, 5.0)
    assert out["next"]["round"] == 2 and out["next"]["steps"][0]["name"] == "page_2"
    out = web_feed.ingest_leaderboard(cache, 4663, 2, {"page_2": page2}, 5.0)
    assert out["done"] and out["count"] == len(page1["data"]) + len(page2["data"])
    with pytest.raises(web_feed.FeedError):
        web_feed.ingest_pools(cache, 4663, {"pools": {"__error": "403"}}, 0)


def test_ingest_positions_two_rounds():
    cache = Cache()
    vault = json.loads(VAULTS.read_text())[0]["data"][0]
    vault["chainId"] = 4663
    payloads = {"owned_auto": {"data": [vault]}, "joined": {"__error": "timeout"}}
    out = web_feed.ingest_positions(cache, 4663, WALLET, 1, payloads, 3.0)
    addr = vault["vaultAddress"].lower()
    assert out["next"]["steps"][0]["name"] == f"detail_{addr}"
    out = web_feed.ingest_positions(
        cache, 4663, WALLET, 2, {f"detail_{addr}": {**vault, "strategies": []}}, 4.0
    )
    assert out["done"] and out["count"] == 1
    entry = cache.peek(("positions", 4663, WALLET))
    assert entry.value[0].owned and entry.upstream_ms == 7.0
    assert web_feed.ingest_positions(cache, 4663, WALLET, 1, {}, 0)["count"] == 0


@pytest.fixture
async def client(monkeypatch):
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["krystal_curator.web_db"]})
    await Tortoise.generate_schemas()
    monkeypatch.setenv("CURATOR_API_SECRET", "web-integration-test-secret-32-characters")
    monkeypatch.setenv("CURATOR_COOKIE_SECURE", "false")
    monkeypatch.delenv("CURATOR_SERVER_FETCH", raising=False)
    from krystal_curator import web_auth

    user = await User.create(address="0x" + "1" * 40)

    async def fake_user():
        return user

    app.dependency_overrides[web_auth.current_user] = fake_user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer web-integration-test-secret-32-characters"},
    ) as c:
        yield c
    app.dependency_overrides.clear()
    await Tortoise.close_connections()


async def test_get_asks_for_feed_then_serves_it(client):
    r = await client.get("/pools?chain=4663")
    assert r.status_code == 200 and "rows" not in r.json()
    recipe = r.json()["needFeed"][0]
    assert recipe["kind"] == "pools"
    r = await client.post(
        "/feed/pools",
        json={
            "chain": 4663,
            "round": 1,
            "upstreamMs": 40,
            "payloads": {"pools": json.loads(FIXTURE.read_text())},
        },
    )
    assert r.status_code == 200 and r.json()["done"]
    r = await client.get("/pools?chain=4663")
    assert r.status_code == 200 and r.headers["x-cache"] == "hit" and len(r.json()["rows"]) > 5
    assert "refreshFeed" not in r.json()
    # Manual refresh in browser-fed mode is a new handshake.
    assert "needFeed" in (await client.get("/pools?chain=4663&fresh=true")).json()
    # Rotations needs both datasets: it asks for the missing one only.
    r = await client.get(f"/rotations?chain=4663&wallet={WALLET}")
    assert [x["kind"] for x in r.json()["needFeed"]] == ["positions"]
    r = await client.post(
        "/feed/positions",
        json={"chain": 4663, "round": 1, "wallet": WALLET, "payloads": {}},
    )
    assert r.json() == {"done": True, "count": 0}
    r = await client.get(f"/rotations?chain=4663&wallet={WALLET}")
    assert r.status_code == 200 and r.json()["rows"] == []
    assert (
        await client.post(
            "/feed/pools",
            json={"chain": 4663, "round": 1, "payloads": {"pools": {"__error": "403"}}},
        )
    ).status_code == 422
