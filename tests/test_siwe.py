"""Sign-In with Ethereum: message grammar, signature recovery, and the nonce-bound endpoints."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("eth_account")

from eth_account import Account
from eth_account.messages import encode_defunct
from tortoise import Tortoise

from krystal_curator import web_siwe
from krystal_curator.web_api import app
from krystal_curator.web_db import Nonce, Preferences, User

ORIGIN = "https://curator.example"
WALLET = Account.create()


def build(
    nonce: str = "abcdef1234567890",
    address: str = WALLET.address,
    domain: str = "curator.example",
    uri: str = f"{ORIGIN}/login",
    statement: str | None = "Sign in to Curator.",
    issued_at: datetime | None = None,
    extra: str = "",
) -> str:
    issued = (issued_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    head = f"{domain} wants you to sign in with your Ethereum account:\n{address}\n\n"
    if statement is not None:
        head += f"{statement}\n"
    return (
        f"{head}\nURI: {uri}\nVersion: 1\nChain ID: 4663\nNonce: {nonce}\nIssued At: {issued}"
        + extra
    )


def sign(text: str, account=WALLET) -> str:
    return account.sign_message(encode_defunct(text=text)).signature.to_0x_hex()


def test_parse_full_message():
    text = build(
        extra=(
            "\nExpiration Time: 2030-01-01T00:00:00Z\nNot Before: 2020-01-01T00:00:00Z"
            "\nRequest ID: r1\nResources:\n- https://a/x\n- ipfs://y"
        )
    )
    m = web_siwe.parse(text)
    assert m.domain == "curator.example"
    assert m.address == WALLET.address
    assert m.statement == "Sign in to Curator."
    assert m.chain_id == 4663
    assert m.nonce == "abcdef1234567890"
    assert m.expiration_time == datetime(2030, 1, 1, tzinfo=UTC)
    assert m.not_before == datetime(2020, 1, 1, tzinfo=UTC)
    assert m.request_id == "r1"
    assert m.resources == ("https://a/x", "ipfs://y")


def test_parse_without_statement_and_with_scheme():
    m = web_siwe.parse(build(statement=None, domain="https://curator.example"))
    assert m.statement is None
    assert m.domain == "curator.example"


@pytest.mark.parametrize(
    "text",
    [
        "hello",
        build(address=WALLET.address.lower()),
        build(nonce="short"),
        build().replace("Version: 1", "Version: 2"),
        build().replace("Chain ID: 4663", "Chain ID: x"),
        build().replace("\nNonce:", "\nNonce:\nNonce:"),
        build(extra="\nIssued At: 2020-01-01T00:00:00Z"),
        build(extra="\nExpiration Time: yesterday"),
        build(statement="a\nb"),
        "x" * (web_siwe.MAX_LENGTH + 1),
    ],
)
def test_parse_rejects(text):
    with pytest.raises(web_siwe.SiweError):
        web_siwe.parse(text)


def test_origin_binding():
    m = web_siwe.parse(build())
    web_siwe.check_origin(m, ORIGIN)
    with pytest.raises(web_siwe.SiweError):
        web_siwe.check_origin(m, "https://evil.example")
    with pytest.raises(web_siwe.SiweError):
        web_siwe.check_origin(web_siwe.parse(build(uri="https://evil.example/")), ORIGIN)
    with pytest.raises(web_siwe.SiweError):
        web_siwe.check_origin(m, "")
    # Local development keeps the port in both host and origin.
    web_siwe.check_origin(
        web_siwe.parse(build(domain="localhost:3000", uri="http://localhost:3000/login")),
        "http://localhost:3000",
    )


def test_time_window():
    now = datetime.now(UTC)
    web_siwe.check_time(web_siwe.parse(build()), now)
    with pytest.raises(web_siwe.SiweError, match="expired"):
        web_siwe.check_time(web_siwe.parse(build(issued_at=now - timedelta(minutes=11))), now)
    with pytest.raises(web_siwe.SiweError, match="future"):
        web_siwe.check_time(web_siwe.parse(build(issued_at=now + timedelta(minutes=11))), now)
    old = build(issued_at=now - timedelta(hours=1), extra="\nExpiration Time: 2999-01-01T00:00:00Z")
    web_siwe.check_time(web_siwe.parse(old), now)
    with pytest.raises(web_siwe.SiweError, match="not valid yet"):
        web_siwe.check_time(web_siwe.parse(build(extra="\nNot Before: 2999-01-01T00:00:00Z")), now)


def test_signature_recovery():
    text = build()
    m = web_siwe.parse(text)
    assert web_siwe.verify_signature(text, m, sign(text)) == WALLET.address
    with pytest.raises(web_siwe.SiweError):
        web_siwe.verify_signature(text, m, sign(text, Account.create()))
    with pytest.raises(web_siwe.SiweError):
        web_siwe.verify_signature(text + " ", m, sign(text))
    with pytest.raises(web_siwe.SiweError):
        web_siwe.verify_signature(text, m, "0x" + "00" * 65)


@pytest.fixture
async def db(monkeypatch):
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["krystal_curator.web_db"]})
    await Tortoise.generate_schemas()
    monkeypatch.setenv("CURATOR_API_SECRET", "web-integration-test-secret-32-characters")
    monkeypatch.setenv("CURATOR_COOKIE_SECURE", "false")
    yield
    await Tortoise.close_connections()


@pytest.fixture
def client(db):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={
            "Authorization": "Bearer web-integration-test-secret-32-characters",
            "X-Curator-Client": "test",
            "X-Curator-Origin": ORIGIN,
        },
    )


async def test_siwe_signs_in_once_per_nonce(client):
    async with client:
        nonce = (await client.get("/auth/nonce")).json()["nonce"]
        text = build(nonce=nonce)
        response = await client.post("/auth/siwe", json={"message": text, "signature": sign(text)})
        assert response.status_code == 200, response.text
        assert response.json() == {"address": WALLET.address}
        assert "HttpOnly" in response.headers["set-cookie"]
        account = (await client.get("/account")).json()
        assert account["email"] is None
        assert account["address"] == WALLET.address
        assert account["settings"]["wallet"] == WALLET.address
        # Replay: nonce consumed.
        response = await client.post("/auth/siwe", json={"message": text, "signature": sign(text)})
        assert response.status_code == 401
        assert await Nonce.all().count() == 0
        assert await User.all().count() == 1
        # Second sign-in of the same wallet reuses the account and keeps its preferences.
        user = await User.get(address=WALLET.address)
        await Preferences.filter(user_id=user.id).update(profile="degen")
        nonce = (await client.get("/auth/nonce")).json()["nonce"]
        text = build(nonce=nonce)
        assert (
            await client.post("/auth/siwe", json={"message": text, "signature": sign(text)})
        ).status_code == 200
        assert await User.all().count() == 1
        assert (await client.get("/account")).json()["settings"]["profile"] == "degen"


async def test_siwe_rejects_unknown_nonce_wrong_origin_and_bad_signature(client):
    async with client:
        text = build(nonce="0123456789abcdef0123456789abcdef")
        response = await client.post("/auth/siwe", json={"message": text, "signature": sign(text)})
        assert response.status_code == 401
        assert "expired" in response.json()["detail"]
        nonce = (await client.get("/auth/nonce")).json()["nonce"]
        text = build(nonce=nonce, domain="evil.example", uri="https://evil.example/")
        response = await client.post("/auth/siwe", json={"message": text, "signature": sign(text)})
        assert response.status_code == 401
        assert "different site" in response.json()["detail"]
        text = build(nonce=nonce)
        response = await client.post(
            "/auth/siwe", json={"message": text, "signature": sign(text, Account.create())}
        )
        assert response.status_code == 401
        # Failed attempts do not burn the nonce; a valid one still succeeds.
        response = await client.post("/auth/siwe", json={"message": text, "signature": sign(text)})
        assert response.status_code == 200, response.text
        assert (
            await client.post("/auth/siwe", json={"message": "hello", "signature": sign("hello")})
        ).status_code == 422
        assert (await client.get("/account")).status_code == 200


async def test_siwe_without_origin_header_fails_closed(db):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer web-integration-test-secret-32-characters"},
    ) as client:
        nonce = (await client.get("/auth/nonce")).json()["nonce"]
        text = build(nonce=nonce)
        response = await client.post("/auth/siwe", json={"message": text, "signature": sign(text)})
        assert response.status_code == 401
        assert "not configured" in response.json()["detail"]
