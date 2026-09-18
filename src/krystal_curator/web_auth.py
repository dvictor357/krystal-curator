"""Local account auth with Argon2 passwords and revocable opaque cookie sessions."""

import hashlib
import hmac
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from starlette.concurrency import run_in_threadpool
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from .models import CHAIN_SLUG
from .web_db import Preferences, RateLimit, Session, User, Watch

COOKIE = "curator_session"
SESSION_SECONDS = 7 * 24 * 3600
passwords = PasswordHash.recommended()
# A missing account still verifies an Argon2 hash to avoid a fast email-enumeration path.
_dummy_hash = passwords.hash(secrets.token_urlsafe(32))
router = APIRouter()


def authorize(authorization: Annotated[str | None, Header()] = None):
    secret = os.environ.get("CURATOR_API_SECRET", "")
    if len(secret) < 32:
        raise HTTPException(503, "Analytics service is not configured.")
    if not hmac.compare_digest(authorization or "", f"Bearer {secret}"):
        raise HTTPException(401, "Unauthorized")


async def throttle(key: str, maximum: int, seconds: int = 60):
    # Row lock makes this shared limit safe across API workers.
    window = int(time.time()) // seconds
    await RateLimit.get_or_create(key=key, defaults={"window": window, "count": 0})
    async with in_transaction() as db:
        row = await RateLimit.filter(key=key).using_db(db).select_for_update().get()
        row.count = row.count + 1 if row.window == window else 1
        row.window = window
        await row.save(using_db=db)
    if row.count > maximum:
        raise HTTPException(
            429, "Too many requests. Please try again later.", headers={"Retry-After": str(seconds)}
        )


async def current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE, "")
    if len(token) != 43:
        raise HTTPException(401, "Please sign in.")
    session = (
        await Session.filter(
            token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at__gt=datetime.now(UTC)
        )
        .select_related("user")
        .first()
    )
    if not session:
        raise HTTPException(401, "Session expired. Please sign in again.")
    return session.user


async def market_user(user: Annotated[User, Depends(current_user)]):
    await throttle(f"market:{user.id}", 20)
    return user


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


async def limit_login(request: Request, email: str):
    # The private bridge overwrites this header; never trust a public forwarded IP.
    peer = request.headers.get("x-curator-client", "local")
    await throttle("auth-ip:" + hashlib.sha256(peer.encode()).hexdigest(), 30, 900)
    await throttle("auth-email:" + hashlib.sha256(email.encode()).hexdigest(), 10, 900)


async def issue_session(response: Response, user: User):
    token = secrets.token_urlsafe(32)
    await Session.filter(expires_at__lte=datetime.now(UTC)).delete()
    await Session.create(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        user=user,
        expires_at=datetime.now(UTC) + timedelta(seconds=SESSION_SECONDS),
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=os.environ.get("CURATOR_COOKIE_SECURE", "true").lower() != "false",
        samesite="lax",
        path="/",
    )


@router.post("/auth/register", status_code=201)
async def register(body: Credentials, request: Request, response: Response):
    email = str(body.email).lower()
    await limit_login(request, email)
    password_hash = await run_in_threadpool(passwords.hash, body.password)
    try:
        user = await User.create(email=email, password_hash=password_hash)
    except IntegrityError:
        raise HTTPException(409, "Unable to create account. Try signing in instead.") from None
    await issue_session(response, user)
    return {"email": user.email}


@router.post("/auth/login")
async def login(body: Credentials, request: Request, response: Response):
    email = str(body.email).lower()
    await limit_login(request, email)
    user = await User.get_or_none(email=email)
    valid = await run_in_threadpool(
        passwords.verify, body.password, user.password_hash if user else _dummy_hash
    )
    if not user or not valid:
        raise HTTPException(401, "Email or password is incorrect.")
    # Rotate the session presented during a login rather than retaining it.
    old = request.cookies.get(COOKIE, "")
    if old:
        await Session.filter(token_hash=hashlib.sha256(old.encode()).hexdigest()).delete()
    await issue_session(response, user)
    return {"email": user.email}


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE, "")
    await Session.filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).delete()
    response.delete_cookie(
        COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=os.environ.get("CURATOR_COOKIE_SECURE", "true").lower() != "false",
    )
    return {"ok": True}


@router.get("/account")
async def account(user: Annotated[User, Depends(current_user)]):
    preferences = await Preferences.filter(user_id=user.id).values(
        "profile", "chain", "source", "size", "wallet"
    )
    watched = (
        await Watch.filter(user_id=user.id)
        .order_by("-created_at")
        .values_list("pool_id", flat=True)
    )
    return {
        "email": user.email,
        "settings": preferences[0] if preferences else None,
        "watchlist": list(watched),
    }


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["conservative", "balanced", "aggressive", "degen"]
    chain: int
    source: Literal["krystal", "rhpools"]
    size: float = Field(ge=1, le=100_000_000, allow_inf_nan=False)
    wallet: str = Field(pattern=r"^(0x[a-fA-F0-9]{40})?$", max_length=42)

    @model_validator(mode="after")
    def valid_chain(self):
        if self.chain not in CHAIN_SLUG or (self.source == "rhpools" and self.chain != 4663):
            raise ValueError("Unsupported network for this source")
        return self


class SettingsAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["settings"]
    settings: Settings


class WatchAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["watch"]
    poolId: str = Field(
        max_length=180, pattern=r"^\d+:[a-zA-Z0-9_-]+:0x[a-fA-F0-9]{40}([a-fA-F0-9]{24})?$"
    )
    watched: bool = Field(strict=True)


@router.post("/account")
async def update_account(
    body: Annotated[SettingsAction | WatchAction, Field(discriminator="action")],
    user: Annotated[User, Depends(current_user)],
):
    await throttle(f"account:{user.id}", 60)
    if isinstance(body, SettingsAction):
        await Preferences.update_or_create(user_id=user.id, defaults=body.settings.model_dump())
    else:
        async with in_transaction() as db:
            await User.filter(id=user.id).using_db(db).select_for_update().get()
            if body.watched:
                count = await Watch.filter(user_id=user.id).using_db(db).count()
                exists = (
                    await Watch.filter(user_id=user.id, pool_id=body.poolId).using_db(db).exists()
                )
                if count >= 500 and not exists:
                    raise HTTPException(422, "Watchlist limit is 500 pools.")
                await Watch.get_or_create(user_id=user.id, pool_id=body.poolId, using_db=db)
            else:
                await Watch.filter(user_id=user.id, pool_id=body.poolId).using_db(db).delete()
    return {"ok": True}
