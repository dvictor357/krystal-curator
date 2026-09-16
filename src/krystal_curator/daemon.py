"""`krystal-curator watch`: headless refresh loop with alerts to stdout and Telegram."""

from __future__ import annotations

import logging
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

from . import api
from .analytics import report_markdown
from .bot import Bot
from .config import Config
from .models import CHAIN_SLUG
from .monitor import Monitor
from .notify import Telegram
from .profiles import PROFILES
from .store import Store
from .vaults import fetch_vaults

log = logging.getLogger("krystal.watch")


def setup_message(p, sigma, profile) -> str:
    """Telegram text: Krystal Automation values for a newly opened position."""
    from .autoconfig import recommend

    su = recommend(p, sigma, profile)
    lines = [
        f"🆕 {p.vault or 'wallet'} {p.pair} [{p.protocol}] {p.value:,.0f}$",
        f"Automation setup ({profile.key}, ±{su.range_pct:g}% / ~{su.hold_days:g}d):",
    ]
    for section, fs in su.by_section().items():
        lines.append(f"— {section}")
        lines += [f"  {f.label}: {f.value}" for f in fs]
    return "\n".join(lines)


def run_watch(
    *,
    chain_id: int,
    wallet: str | None,
    interval: int,
    profile: str,
    telegram: bool,
    digest_hour: int | None,
    once: bool = False,
    config: Config | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = config or Config()
    store = Store()
    mon = Monitor(
        store, profile=PROFILES[profile], alerts=cfg.alerts, snapshot_days=cfg.snapshot_days
    )
    ticks = 0
    tg = Telegram.from_env() if telegram else None
    if telegram and tg is None:
        log.error("telegram requested but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing")
        return 2
    if tg:
        name = tg.whoami()
        if not name:
            log.error("telegram token rejected by getMe")
            return 2
        log.info("telegram bot @%s ready", name)
        tg.send(
            f"krystal-curator watch started · {CHAIN_SLUG.get(chain_id, chain_id)} · "
            f"every {interval}s · profile {profile}"
            + (f" · wallet {wallet[:6]}…{wallet[-4:]}" if wallet else "")
        )

    bot = Bot(tg, store, cfg, mon) if tg else None
    if bot:
        log.info("telegram commands enabled (/help)")
        from .bot import reply_keyboard

        tg.send("buttons ready — /menu any time", reply_markup=reply_keyboard())

    stop = False

    def _sig(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    last_digest_day: str | None = None
    seen_ids: set[str] = set()
    while not stop:
        t0 = time.time()
        try:
            pools = api.fetch_pools(chain_id, **cfg.fetch_kwargs)
        except api.KrystalError as e:
            log.error("pools: %s", e)
            pools = None
        vaults = None
        if wallet:
            try:
                vaults = fetch_vaults(wallet, chain_id=chain_id)
            except api.KrystalError as e:
                log.error("vaults: %s", e)
        if pools is not None:
            alerts = mon.tick(pools, vaults)
            opens = mon.open_positions()
            oor = sum(1 for p in opens if not p.in_range)
            log.info(
                "tick: %d pools, %d vaults, %d open (%d OOR), %d alerts",
                len(pools),
                len(mon.vaults),
                len(opens),
                oor,
                len(alerts),
            )
            for a in alerts:
                log.warning("%s: %s", a.title, a.text)
            ticks += 1
            store.kv_set(
                "watch.heartbeat",
                {
                    "ts": time.time(),
                    "interval": interval,
                    "ticks": ticks,
                    "pools": len(pools),
                    "vaults": len(mon.vaults),
                    "open": len(opens),
                    "oor": oor,
                    "telegram": bool(tg),
                    "chain": chain_id,
                },
            )
            if alerts:
                prev = store.kv_get("watch.last_alerts") or []
                when = datetime.now(UTC).strftime("%m-%d %H:%M")
                prev += [{"when": when, "title": a.title, "text": a.text} for a in alerts]
                store.kv_set("watch.last_alerts", prev[-50:])
            new_ids = {p.id for p in opens} - seen_ids
            if seen_ids and new_ids:
                for p in opens:
                    if p.id in new_ids:
                        msg = setup_message(p, mon.sigma_for(p), mon.profile)
                        log.info("new position %s — setup suggestion sent", p.pair)
                        if tg:
                            tg.send(msg)
            seen_ids |= {p.id for p in opens}
            if tg and alerts and not (bot and bot.muted):
                icon = {"error": "🔴", "warning": "🟠", "information": "🟢"}
                tg.send(
                    "\n".join(f"{icon.get(a.severity, '•')} {a.title}: {a.text}" for a in alerts)
                )

            now = datetime.now(UTC)
            if (
                digest_hour is not None
                and mon.vaults
                and now.hour == digest_hour
                and last_digest_day != now.strftime("%Y-%m-%d")
            ):
                last_digest_day = now.strftime("%Y-%m-%d")
                equity = {
                    v.address: [h.tvl for h in store.vault_history(v.chain_id, v.address)]
                    for v in mon.vaults
                }
                md = report_markdown(
                    mon.vaults, chain=CHAIN_SLUG.get(chain_id, str(chain_id)), equity=equity
                )
                out = Path("reports")
                out.mkdir(exist_ok=True)
                path = out / f"vaults_{chain_id}_{now:%Y%m%d}.md"
                path.write_text(md, encoding="utf-8")
                log.info("digest written %s", path)
                if tg:
                    summary = "\n".join(
                        f"{v.name}: tvl {v.tvl:,.0f}$ · 24h {v.earning_24h:+,.0f}$ · pnl {v.pnl:+,.0f}$ · "
                        f"{len(v.positions)} open"
                        for v in mon.vaults
                    )
                    tg.send_file(path, caption=f"Daily vault digest {now:%Y-%m-%d}\n{summary}")
        if once:
            break
        sleep = max(5.0, interval - (time.time() - t0))
        deadline = time.time() + sleep
        while not stop and time.time() < deadline:
            if bot:
                bot.poll(timeout=min(20, max(1, int(deadline - time.time()))))
            else:
                time.sleep(1)
    if tg:
        tg.send("krystal-curator watch stopped")
    log.info("stopped")
    return 0
