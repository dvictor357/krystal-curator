"""Usage metering: one counter row per user, day and route, flushed in batches.

Every authenticated request increments an in-memory bucket; a background task writes the
buckets to `curator_usage` every FLUSH_SECONDS (and at shutdown). Reads are admin-only and
aggregate: active users, requests per route, top accounts by requests.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, Request
from tortoise.exceptions import IntegrityError
from tortoise.expressions import F

from .web_db import Usage, User

log = logging.getLogger(__name__)
FLUSH_SECONDS = 15
_buckets: dict[tuple[str, date, str], list[float]] = defaultdict(lambda: [0, 0, 0.0])
_lock = asyncio.Lock()


def record(user_id: str, route: str, status: int, ms: float) -> None:
    b = _buckets[(user_id, datetime.now(UTC).date(), route[:60])]
    b[0] += 1
    b[1] += int(status >= 400)
    b[2] += ms


async def flush() -> int:
    async with _lock:
        pending = dict(_buckets)
        _buckets.clear()
    written = 0
    for (user_id, day, route), (count, errors, ms_total) in pending.items():
        try:
            row, _ = await Usage.get_or_create(
                user_id=user_id, day=day, route=route, defaults={"count": 0}
            )
            await Usage.filter(id=row.id).update(
                count=F("count") + count,
                errors=F("errors") + errors,
                ms_total=F("ms_total") + ms_total,
            )
        except IntegrityError:
            continue  # account deleted between the request and the flush: nothing to keep
        written += 1
    return written


async def loop() -> None:
    while True:
        await asyncio.sleep(FLUSH_SECONDS)
        try:
            await flush()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("usage: flush failed")


async def middleware(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    user = getattr(request.state, "user", None)
    if user is not None:
        route = getattr(request.scope.get("route"), "path", request.url.path)
        record(
            str(user.id),
            f"{request.method} {route}",
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
    return response


def admin_addresses() -> set[str]:
    return {
        a.strip().lower()
        for a in os.environ.get("CURATOR_ADMIN_ADDRESSES", "").split(",")
        if a.strip()
    }


def is_admin(user: User) -> bool:
    return bool(user.address) and user.address.lower() in admin_addresses()


def require_admin(user: User) -> None:
    if not is_admin(user):
        raise HTTPException(403, "Admin only.")


async def report(days: int = 30) -> dict:
    await flush()
    since = datetime.now(UTC).date() - timedelta(days=days - 1)
    rows = await Usage.filter(day__gte=since).select_related("user")
    per_day: dict[str, dict] = defaultdict(lambda: {"requests": 0, "users": set()})
    per_route: dict[str, dict] = defaultdict(
        lambda: {"requests": 0, "errors": 0, "ms": 0.0, "users": set()}
    )
    per_user: dict[str, dict] = defaultdict(lambda: {"requests": 0, "days": set(), "label": ""})
    for r in rows:
        d = r.day.isoformat()
        per_day[d]["requests"] += r.count
        per_day[d]["users"].add(str(r.user_id))
        pr = per_route[r.route]
        pr["requests"] += r.count
        pr["errors"] += r.errors
        pr["ms"] += r.ms_total
        pr["users"].add(str(r.user_id))
        pu = per_user[str(r.user_id)]
        pu["requests"] += r.count
        pu["days"].add(d)
        u = r.user
        pu["label"] = (u.address[:6] + "…" + u.address[-4:]) if u.address else (u.email or "?")
    active_7d = {
        str(r.user_id) for r in rows if r.day >= datetime.now(UTC).date() - timedelta(days=6)
    }
    return {
        "days": days,
        "totalUsers": await User.all().count(),
        "activeUsers": len({str(r.user_id) for r in rows}),
        "activeUsers7d": len(active_7d),
        "requests": sum(r.count for r in rows),
        "perDay": [
            {"day": d, "requests": v["requests"], "users": len(v["users"])}
            for d, v in sorted(per_day.items())
        ],
        "perRoute": sorted(
            (
                {
                    "route": k,
                    "requests": v["requests"],
                    "errors": v["errors"],
                    "avgMs": v["ms"] / v["requests"] if v["requests"] else 0,
                    "users": len(v["users"]),
                }
                for k, v in per_route.items()
            ),
            key=lambda x: -x["requests"],
        ),
        "topUsers": sorted(
            (
                {"label": v["label"], "requests": v["requests"], "activeDays": len(v["days"])}
                for v in per_user.values()
            ),
            key=lambda x: -x["requests"],
        )[:20],
    }
