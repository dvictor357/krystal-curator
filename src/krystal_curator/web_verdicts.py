"""Verdict log: remember what we told a user about each position, then hold ourselves to it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .web_db import User, Verdict

RELOG_AFTER = timedelta(hours=6)  # same verdict again → one row per 6 h, not per page view
OUTCOME_MIN_AGE = timedelta(hours=24)  # judge a verdict only after a day has passed
OUTCOME_WINDOW = timedelta(days=14)


def _same(a: Verdict, row: dict) -> bool:
    best = row["best"] or {}
    return a.kind == row["kind"] and a.best_pool_id == best.get("poolId", "")


async def log_rows(user: User, rows: list[dict]) -> None:
    """Insert a verdict per position when it changed, or when the last one is 6 h old."""
    ids = [r["id"] for r in rows]
    if not ids:
        return
    latest: dict[str, Verdict] = {}
    async for v in Verdict.filter(user_id=user.id, position_id__in=ids).order_by("-at"):
        latest.setdefault(v.position_id, v)
    now = datetime.now(UTC)
    fresh = [
        Verdict(
            user_id=user.id,
            position_id=r["id"],
            pair=r["pair"][:60],
            kind=r["kind"],
            best_pool=(r["best"] or {}).get("pair", "")[:60],
            best_pool_id=(r["best"] or {}).get("poolId", "")[:180],
            uplift_day=(r["best"] or {}).get("upliftDay") or 0.0,
            payback_days=(r["best"] or {}).get("paybackDays"),
            value=r["value"],
            current_net_day=r["current"]["netDay"],
            fees_total=r["current"]["feesTotal"],
            age_days=r["current"]["ageDays"],
        )
        for r in rows
        if r["id"] not in latest
        or not _same(latest[r["id"]], r)
        or now - latest[r["id"]].at >= RELOG_AFTER
    ]
    if fresh:
        await Verdict.bulk_create(fresh)


def history_for(row: dict, verdicts: list[Verdict], now: datetime | None = None) -> dict | None:
    """Streak of the current verdict, the one before it, and how an older call played out.

    `verdicts` newest first, one position. Outcome compares the realised fee rate since a
    verdict ≥ 24 h old with the net/day we predicted for staying; uplift is what we claimed
    the best alternative would add on top.
    """
    now = now or datetime.now(UTC)
    if not verdicts:
        return None
    head = verdicts[0]
    since = head.at
    previous: Verdict | None = None
    for v in verdicts:
        if v.kind == head.kind and v.best_pool_id == head.best_pool_id:
            since = v.at
        else:
            previous = v
            break
    reference = next(
        (v for v in reversed(verdicts) if OUTCOME_MIN_AGE <= now - v.at <= OUTCOME_WINDOW),
        None,
    )
    outcome = None
    if reference is not None:
        days = (now - reference.at).total_seconds() / 86400
        realised = (row["current"]["feesTotal"] - reference.fees_total) / days
        outcome = {
            "at": reference.at.timestamp(),
            "days": days,
            "kind": reference.kind,
            "bestPool": reference.best_pool,
            "predictedNetDay": reference.current_net_day,
            "predictedUpliftDay": reference.uplift_day,
            "realisedFeeDay": realised,
        }
    return {
        "since": since.timestamp(),
        "count": len(verdicts),
        "previous": (
            {"kind": previous.kind, "bestPool": previous.best_pool, "at": previous.at.timestamp()}
            if previous
            else None
        ),
        "outcome": outcome,
    }


async def attach_history(user: User, rows: list[dict]) -> None:
    ids = [r["id"] for r in rows]
    if not ids:
        return
    cutoff = datetime.now(UTC) - OUTCOME_WINDOW - timedelta(days=1)
    grouped: dict[str, list[Verdict]] = {}
    async for v in Verdict.filter(user_id=user.id, position_id__in=ids, at__gte=cutoff).order_by(
        "-at"
    ):
        grouped.setdefault(v.position_id, []).append(v)
    for r in rows:
        r["history"] = history_for(r, grouped.get(r["id"], []))
