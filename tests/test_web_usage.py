"""Usage metering: counted after auth, flushed in batches, read by admins only."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi import Request

pytest.importorskip("fastapi")

from tortoise import Tortoise

from krystal_curator import web_usage
from krystal_curator.web_api import app
from krystal_curator.web_db import Usage, User

FIXTURE = Path(__file__).parent / "fixtures" / "top_pools_robinhood.json"
ADMIN = "0x" + "a" * 40


@pytest.fixture
async def client(monkeypatch):
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["krystal_curator.web_db"]})
    await Tortoise.generate_schemas()
    monkeypatch.setenv("CURATOR_API_SECRET", "web-integration-test-secret-32-characters")
    monkeypatch.setenv("CURATOR_ADMIN_ADDRESSES", ADMIN)
    monkeypatch.delenv("CURATOR_SERVER_FETCH", raising=False)
    from krystal_curator import web_auth

    users = {
        "admin": await User.create(address=ADMIN),
        "bob": await User.create(address="0x" + "b" * 40),
    }
    who = {"name": "admin"}

    async def fake_user(request: Request):
        user = users[who["name"]]
        request.state.user = user
        return user

    app.dependency_overrides[web_auth.current_user] = fake_user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer web-integration-test-secret-32-characters"},
    ) as c:
        yield c, who
    app.dependency_overrides.clear()
    web_usage._buckets.clear()
    await Tortoise.close_connections()


async def test_requests_are_metered_and_admin_can_read(client):
    c, who = client
    await c.get("/pools?chain=4663")  # needFeed answer, still a request
    await c.post(
        "/feed/pools",
        json={"chain": 4663, "round": 1, "payloads": {"pools": json.loads(FIXTURE.read_text())}},
    )
    await c.get("/pools?chain=4663")
    who["name"] = "bob"
    await c.get("/pools?chain=8453")
    assert await Usage.all().count() == 0  # buffered
    assert (
        await web_usage.flush() == 3
    )  # (admin, GET /pools), (admin, POST /feed), (bob, GET /pools)
    rows = {(str(r.user_id), r.route): r.count for r in await Usage.all()}
    assert rows[(str((await User.get(address=ADMIN)).id), "GET /pools")] == 2
    assert rows[(str((await User.get(address=ADMIN)).id), "POST /feed/{kind}")] == 1
    r = await c.get("/usage")
    assert r.status_code == 403
    who["name"] = "admin"
    r = await c.get("/usage?days=7")
    assert r.status_code == 200
    body = r.json()
    assert body["activeUsers"] == 2 and body["requests"] >= 4 and body["totalUsers"] == 2
    assert body["perRoute"][0]["route"] == "GET /pools"
    assert all("0x" + "b" * 40 not in u["label"] for u in body["topUsers"])  # shortened labels only
    assert (await c.get("/account")).json()["admin"] is True
    who["name"] = "bob"
    assert (await c.get("/account")).json()["admin"] is False
