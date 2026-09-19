"""Verdict log: remember what we told a user about each position, then hold ourselves to it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .web_db import PoolSample, User, Verdict

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
            best_fee_day=(r["best"] or {}).get("feeDay") or 0.0,
            best_il_day=(r["best"] or {}).get("ilDay") or 0.0,
            cost=r["cost"],
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


# ---- pool samples + aggregate track record ---------------------------------------------

SAMPLE_EVERY = timedelta(hours=1)


async def record_samples(rows: list[dict]) -> int:
    """Remember fee24/TVL of every current and best pool in `rows`, at most hourly per pool."""
    wanted: dict[str, tuple[float, float]] = {}
    for r in rows:
        cur, best = r["current"], r["best"] or {}
        if cur.get("poolId") and cur.get("poolFee24") is not None:
            wanted[cur["poolId"]] = (cur["poolFee24"], cur["poolTvl"] or 0.0)
        if best.get("poolId") and best.get("poolFee24") is not None:
            wanted[best["poolId"]] = (best["poolFee24"], best.get("tvl") or 0.0)
    if not wanted:
        return 0
    cutoff = datetime.now(UTC) - SAMPLE_EVERY
    recent = set(
        await PoolSample.filter(pool_id__in=list(wanted), at__gte=cutoff)
        .distinct()
        .values_list("pool_id", flat=True)
    )
    fresh = [
        PoolSample(pool_id=pid, fee24=fee, tvl=tvl)
        for pid, (fee, tvl) in wanted.items()
        if pid not in recent
    ]
    if fresh:
        await PoolSample.bulk_create(fresh)
    return len(fresh)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def judge(
    verdict: Verdict,
    later: Verdict | None,
    samples: list[PoolSample],
    now: datetime,
) -> dict | None:
    """One verdict against what followed. None when there is not enough evidence yet.

    `later` = the newest verdict for the same position (carries the latest fees_total);
    `samples` = pool samples for the alternative between the verdict and now.
    """
    if later is None or later.at <= verdict.at:
        return None
    days = (later.at - verdict.at).total_seconds() / 86400
    if days < 1:
        return None
    realised_fee_day = (later.fees_total - verdict.fees_total) / days
    out = {
        "kind": verdict.kind,
        "days": days,
        "predictedNetDay": verdict.current_net_day,
        "realisedFeeDay": realised_fee_day,
    }
    if verdict.kind in ("rotate", "consider") and verdict.best_pool_id:
        window = [s for s in samples if verdict.at <= s.at <= later.at]
        if len(window) < 2:
            return out | {"alternative": None}
        share = [
            s.fee24 * (verdict.value / (s.tvl + verdict.value))
            if s.tvl + verdict.value > 0
            else 0.0
            for s in window
        ]
        alt_fee_day = sum(share) / len(share)
        alt_net_day = alt_fee_day - verdict.best_il_day
        # Realised uplift, fees vs fees, after amortising the switch cost over the days seen.
        realised_uplift = alt_fee_day - realised_fee_day - verdict.cost / days
        out["alternative"] = {
            "samples": len(window),
            "predictedFeeDay": verdict.best_fee_day,
            "realisedFeeDay": alt_fee_day,
            "realisedNetDay": alt_net_day,
            "predictedUpliftDay": verdict.uplift_day,
            "realisedUpliftDay": realised_uplift,
            "hit": realised_uplift > 0,
        }
    return out


async def track_record(days: int = 30, now: datetime | None = None) -> dict:
    """Everything we said in the window, judged where a day or more has passed.

    Aggregated across all users and anonymised: no wallets, positions or pools leave here.
    """
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    verdicts = await Verdict.filter(at__gte=since).order_by("at")
    counts = {"rotate": 0, "consider": 0, "stay": 0, "none": 0}
    for v in verdicts:
        counts[v.kind] = counts.get(v.kind, 0) + 1
    latest: dict[tuple, Verdict] = {}
    for v in verdicts:  # ascending → last write is the newest per position
        latest[(v.user_id, v.position_id)] = v
    pool_ids = {v.best_pool_id for v in verdicts if v.best_pool_id}
    samples: dict[str, list[PoolSample]] = {}
    if pool_ids:
        async for s in PoolSample.filter(pool_id__in=list(pool_ids), at__gte=since).order_by("at"):
            samples.setdefault(s.pool_id, []).append(s)
    judged = []
    for v in verdicts:
        outcome = judge(
            v, latest.get((v.user_id, v.position_id)), samples.get(v.best_pool_id, []), now
        )
        if outcome:
            judged.append(outcome)
    stay = [o for o in judged if o["predictedNetDay"] is not None]
    alts = [o["alternative"] for o in judged if o.get("alternative")]
    ratio = [
        o["realisedFeeDay"] / o["predictedNetDay"] for o in stay if o["predictedNetDay"] > 0.05
    ]
    return {
        "windowDays": days,
        "generatedAt": now.timestamp(),
        "verdicts": {"total": len(verdicts), **counts},
        "users": len({v.user_id for v in verdicts}),
        "positions": len(latest),
        "judged": len(judged),
        "stay": {
            "n": len(stay),
            "medianPredictedNetDay": _median([o["predictedNetDay"] for o in stay]),
            "medianRealisedFeeDay": _median([o["realisedFeeDay"] for o in stay]),
            "medianRealisedOverPredicted": _median(ratio),
        },
        "rotate": {
            "n": len(alts),
            "hitRate": (sum(1 for a in alts if a["hit"]) / len(alts)) if alts else None,
            "medianPredictedUpliftDay": _median([a["predictedUpliftDay"] for a in alts]),
            "medianRealisedUpliftDay": _median([a["realisedUpliftDay"] for a in alts]),
            "medianDays": _median([o["days"] for o in judged if o.get("alternative")]),
        },
        "poolSamples": sum(len(v) for v in samples.values()),
    }
