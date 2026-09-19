"""Per-user position alerts over Telegram: range, edge, grade decay, PnL drop, verdict flips.

One asyncio loop per API process; a DB lease (`Job`) makes sure only one process runs a
tick per interval. Rules come from `monitor.Monitor.position_alerts` (shared with the TUI
and the `watch` daemon) plus a rotation-verdict rule on top of `web_rotation`.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
from datetime import UTC, datetime, timedelta

from starlette.concurrency import run_in_threadpool

from . import api, chain_rpc, notify, vaults, web_feed, web_rotation, web_verdicts
from .models import Pool, default_quote
from .monitor import Alert, Monitor
from .profiles import PROFILES
from .vaults import Vault
from .web_cache import Cache
from .web_db import AlertState, Job, Preferences

log = logging.getLogger(__name__)
INTERVAL = int(os.environ.get("CURATOR_ALERT_INTERVAL", "300"))
JOB = "alerts"


def telegram(chat_id: str) -> notify.Telegram | None:
    token = os.environ.get(notify.TOKEN_ENV, "")
    return notify.Telegram(token, chat_id) if token and chat_id else None


async def send_test(chat_id: str) -> bool | None:
    """None = no bot token on this deployment; False = Telegram refused (bot not started)."""
    bot = telegram(chat_id)
    if bot is None:
        return None
    return await run_in_threadpool(
        bot.send, "Curator alerts are connected. You will hear from me when a position needs you."
    )


def evaluate(
    prefs: Preferences,
    user_vaults: list[Vault],
    pools: list[Pool],
    previous: dict[str, dict],
) -> tuple[list[Alert], dict[str, dict]]:
    """Alerts for one user given last tick's state; returns the state to store."""
    profile = PROFILES.get(prefs.profile, PROFILES["balanced"])
    monitor = Monitor(store=None, profile=profile, pools=pools, vaults=user_vaults)  # type: ignore[arg-type]
    monitor.pos_state = {k: dict(v) for k, v in previous.items()}
    alerts = monitor.position_alerts()
    live = {p.id for p in monitor.open_positions()}
    state = {k: v for k, v in monitor.pos_state.items() if k in live}  # closed ones drop out
    first = not previous
    for row in web_rotation.rotation_rows(
        user_vaults, pools, profile, quote=default_quote(prefs.chain)
    ):
        prev = previous.get(row["id"], {})
        best = row["best"] or {}
        if not first and row["kind"] == "rotate" and prev.get("kind") != "rotate":
            alerts.append(Alert("ROTATE", f"{row['pair']}: {row['verdict']}", "warning"))
        elif (
            not first
            and prev.get("kind") == "rotate"
            and row["kind"] != "rotate"
            and prev.get("best_pool_id")
        ):
            alerts.append(
                Alert(
                    "ROTATE",
                    f"{row['pair']}: rotation window closed — {row['verdict']}",
                    "information",
                )
            )
        state.setdefault(row["id"], {}).update(
            {"kind": row["kind"], "best_pool_id": best.get("poolId", "")}
        )
    return alerts, state


def format_message(alerts: list[Alert]) -> str:
    icon = {"error": "🔴", "warning": "🟠", "information": "🟢"}
    lines = [f"{icon.get(a.severity, '•')} <b>{a.title}</b> — {_escape(a.text)}" for a in alerts]
    return "<b>Curator</b>\n" + "\n".join(lines)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def claim(name: str, seconds: int) -> bool:
    now = datetime.now(UTC)
    until = now + timedelta(seconds=seconds)
    _, created = await Job.get_or_create(name=name, defaults={"locked_until": until})
    if created:
        return True
    # Atomic: only the row still expired is updated; one process wins.
    updated = await Job.filter(name=name, locked_until__lte=now).update(locked_until=until)
    return updated == 1


POSITIONS_MAX_AGE = 24 * 3600  # browser-fed positions: ranges are static, so a day is fine
POOLS_MAX_AGE = 30 * 60  # browser-fed pool metrics: older than this and verdicts are noise


def load_feeds(cache: Cache, prefs: Preferences):
    """(positions_entry, pools_entry) for one user, or None when nothing usable is there.

    Server-fetch deployments load from Krystal; browser-fed ones can only use what this
    user's browser posted (per-user keys), within an age that still makes sense.
    """
    pkey = ("positions", prefs.chain, prefs.wallet.lower())
    qkey = ("pools", prefs.chain, prefs.source)
    if web_feed.server_fetch_enabled():
        try:
            positions_entry, _ = cache.get(
                pkey, lambda: vaults.fetch_vaults(prefs.wallet, chain_id=prefs.chain), 60, 600
            )
            pools_entry, _ = cache.get(
                qkey, lambda: api.fetch_pools(prefs.chain, source=prefs.source), 60, 600
            )
        except Exception as e:  # noqa: BLE001 — one user's feed failure must not stop the loop
            log.warning("alerts: skipping %s: %s", prefs.user_id, e)
            return None
        return positions_entry, pools_entry
    scope = str(prefs.user_id)
    positions_entry = cache.peek((*pkey, scope))
    pools_entry = cache.peek((*qkey, scope))
    now = time.time()
    if positions_entry is None or now - positions_entry.at > POSITIONS_MAX_AGE:
        return None
    if pools_entry is None or now - pools_entry.at > POOLS_MAX_AGE:
        return None
    return positions_entry, pools_entry


async def tick(cache: Cache) -> int:
    """One pass over every user with alerts on; returns how many messages were sent."""
    sent = 0
    prefs_rows = (
        await Preferences.filter(alerts=True)
        .exclude(telegram_chat_id="")
        .exclude(wallet="")
        .select_related("user")
    )
    for prefs in prefs_rows:
        bot = telegram(prefs.telegram_chat_id)
        if bot is None:
            return 0
        loaded = await run_in_threadpool(load_feeds, cache, prefs)
        if loaded is None:
            continue
        positions_entry, pools_entry = loaded
        # Range and edge rules run on the live chain price, not the feed's last snapshot.
        user_vaults = [copy.deepcopy(v) for v in positions_entry.value]
        try:
            await run_in_threadpool(
                chain_rpc.refresh_prices,
                prefs.chain,
                [p for v in user_vaults for p in v.positions],
                pools_entry.value,
            )
        except Exception as e:  # noqa: BLE001 — RPC trouble degrades to feed prices
            log.warning("alerts: rpc price refresh failed for %s: %s", prefs.chain, e)
        previous = {s.position_id: s.state async for s in AlertState.filter(user_id=prefs.user_id)}
        alerts, state = evaluate(prefs, user_vaults, pools_entry.value, previous)
        # Keep the verdict log and pool samples moving for this user even between page views.
        rows = web_rotation.rotation_rows(
            user_vaults,
            pools_entry.value,
            PROFILES.get(prefs.profile, PROFILES["balanced"]),
            quote=default_quote(prefs.chain),
        )
        await web_verdicts.log_rows(prefs.user, rows)
        await web_verdicts.record_samples(rows)
        for position_id, value in state.items():
            await AlertState.update_or_create(
                user_id=prefs.user_id, position_id=position_id[:120], defaults={"state": value}
            )
        stale = set(previous) - set(state)
        if stale:
            await AlertState.filter(user_id=prefs.user_id, position_id__in=list(stale)).delete()
        if alerts:
            ok = await run_in_threadpool(bot.send, format_message(alerts), html=True)
            sent += int(bool(ok))
    return sent


async def loop(cache: Cache) -> None:
    if os.environ.get("CURATOR_ALERTS", "true").lower() == "false":
        return
    if not os.environ.get(notify.TOKEN_ENV):
        log.info("alerts: %s unset, loop idle", notify.TOKEN_ENV)
        return
    await asyncio.sleep(5)
    while True:
        try:
            if await claim(JOB, INTERVAL - 5):
                sent = await tick(cache)
                if sent:
                    log.info("alerts: %d message(s) sent", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("alerts: tick failed")
        await asyncio.sleep(INTERVAL)
