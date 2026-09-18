"""Per-user position alerts over Telegram: range, edge, grade decay, PnL drop, verdict flips.

One asyncio loop per API process; a DB lease (`Job`) makes sure only one process runs a
tick per interval. Rules come from `monitor.Monitor.position_alerts` (shared with the TUI
and the `watch` daemon) plus a rotation-verdict rule on top of `web_rotation`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from starlette.concurrency import run_in_threadpool

from . import api, notify, vaults, web_rotation
from .models import Pool
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
        user_vaults, pools, profile, quote=None if prefs.source == "rhpools" else "USDG"
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
        try:
            positions_entry, _ = await run_in_threadpool(
                cache.get,
                ("positions", prefs.chain, prefs.wallet.lower()),
                lambda p=prefs: vaults.fetch_vaults(p.wallet, chain_id=p.chain),
                60,
                600,
            )
            pools_entry, _ = await run_in_threadpool(
                cache.get,
                ("pools", prefs.chain, prefs.source),
                lambda p=prefs: api.fetch_pools(p.chain, source=p.source),
                60,
                600,
            )
        except Exception as e:  # noqa: BLE001 — one user's feed failure must not stop the loop
            log.warning("alerts: skipping %s: %s", prefs.user_id, e)
            continue
        previous = {s.position_id: s.state async for s in AlertState.filter(user_id=prefs.user_id)}
        alerts, state = evaluate(prefs, positions_entry.value, pools_entry.value, previous)
        for position_id, value in state.items():
            await AlertState.update_or_create(
                user_id=prefs.user_id, position_id=position_id, defaults={"state": value}
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
