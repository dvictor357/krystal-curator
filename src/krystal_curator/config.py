"""Configuration: one `config.toml`, overridable by env and CLI flags.

Precedence (highest first): CLI flag > environment variable > config.toml > built-in default.

Lookup order for the file: `--config PATH`, `$KRYSTAL_CONFIG`, `./config.toml`,
`<user config dir>/krystal-curator/config.toml`. Secrets stay in `.env` / the environment,
never in config.toml (it is meant to be committed or shared).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_data_dir

from .models import ROBINHOOD

CONFIG_ENV = "KRYSTAL_CONFIG"
DATA_DIR_ENV = "KRYSTAL_DATA_DIR"
FILE_NAME = "config.toml"


def data_dir() -> Path:
    """Where the sqlite db, logo cache and heartbeat live (override for containers)."""
    return Path(os.environ.get(DATA_DIR_ENV) or user_data_dir("krystal-curator"))


@dataclass(slots=True)
class Alerts:
    pos_pnl_drop: float = 0.05  # fraction of position value lost between ticks
    edge_sigma: float = 0.5  # nearest range edge closer than this many daily σ
    watch_tvl_move: float = 30.0  # % TVL move in an hour on a starred pool
    watch_fee_drop: float = -50.0  # % fee24 change on a starred pool
    watch_drawdown: float = -30.0  # % drawdown on a starred pool


@dataclass(slots=True)
class Config:
    chain: int = ROBINHOOD
    pool_source: str = "krystal"  # krystal | rhpools (chain-indexed, Robinhood only)
    rhpools_url: str = "https://rhpools.lol"  # or a local `rhpools --port 8196`
    rhpools_top: int = 150  # pools per window pulled from rhpools (150 = one request)
    # windows to request; empty = 1h+24h on a public host, all four on a local rhpools
    rhpools_windows: list[str] = field(default_factory=list)
    reconcile: bool = False  # also fetch the other feed and show SRCΔ (Robinhood only)
    quote: str = "USDG"  # "any" disables
    profile: str = "balanced"
    protocols: list[str] = field(default_factory=list)
    size: float = 50_000
    wallet: str = ""  # or KRYSTAL_WALLET
    refresh: int = 300  # TUI auto-refresh seconds, 0 = off
    images: str = ""  # auto | tgp | sixel | halfcell | unicode | off; "" = detect
    interval: int = 300  # watch daemon seconds
    telegram: bool = False
    digest_hour: int | None = None  # UTC hour for the daily report
    rotate_cost_pct: float = 0.3
    snapshot_days: int = 14
    alerts: Alerts = field(default_factory=Alerts)
    source: Path | None = None  # file it was loaded from, if any

    @property
    def quote_or_none(self) -> str | None:
        return None if self.quote.lower() in ("", "any") else self.quote

    @property
    def fetch_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for `api.fetch_pools` selecting the configured feed."""
        return {
            "source": self.pool_source,
            "rhpools_url": self.rhpools_url,
            "rhpools_top": self.rhpools_top,
            "rhpools_windows": list(self.rhpools_windows),
        }


def find_path(explicit: str | Path | None = None) -> Path | None:
    candidates = [
        Path(explicit) if explicit else None,
        Path(os.environ[CONFIG_ENV]) if os.environ.get(CONFIG_ENV) else None,
        Path.cwd() / FILE_NAME,
        Path(user_config_dir("krystal-curator")) / FILE_NAME,
    ]
    for c in candidates:
        if c and c.is_file():
            return c
    return None


_ENV_MAP = {  # env var → config field (secrets excluded on purpose)
    "KRYSTAL_CHAIN": "chain",
    "KRYSTAL_SOURCE": "pool_source",
    "KRYSTAL_RHPOOLS_URL": "rhpools_url",
    "KRYSTAL_RHPOOLS_WINDOWS": "rhpools_windows",
    "KRYSTAL_RECONCILE": "reconcile",
    "KRYSTAL_QUOTE": "quote",
    "KRYSTAL_PROFILE": "profile",
    "KRYSTAL_SIZE": "size",
    "KRYSTAL_WALLET": "wallet",
    "KRYSTAL_REFRESH": "refresh",
    "KRYSTAL_IMAGE": "images",
    "KRYSTAL_INTERVAL": "interval",
    "KRYSTAL_TELEGRAM": "telegram",
    "KRYSTAL_DIGEST_HOUR": "digest_hour",
}


def _coerce(cfg: Config, name: str, raw: Any) -> Any:
    kind = {f.name: f.type for f in fields(Config)}[name]
    if kind in ("int", "int | None"):
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "bool":
        return str(raw).lower() in ("1", "true", "yes", "on")
    if kind == "list[str]":
        return (
            [x.strip() for x in str(raw).split(",") if x.strip()]
            if isinstance(raw, str)
            else list(raw)
        )
    return str(raw)


def load(explicit: str | Path | None = None) -> Config:
    cfg = Config()
    path = find_path(explicit)
    if path:
        data = tomllib.loads(path.read_text())
        for k, v in data.items():
            if k == "alerts" and isinstance(v, dict):
                for ak, av in v.items():
                    if hasattr(cfg.alerts, ak):
                        setattr(cfg.alerts, ak, float(av))
            elif hasattr(cfg, k) and k not in ("source", "alerts"):
                setattr(cfg, k, _coerce(cfg, k, v))
        cfg.source = path
    for env, name in _ENV_MAP.items():
        if os.environ.get(env):
            setattr(cfg, name, _coerce(cfg, name, os.environ[env]))
    return cfg


TEMPLATE = """# krystal-curator configuration. Precedence: CLI flag > env var > this file > default.
# Secrets (KRYSTAL_CLOUD_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) go in .env, not here.

chain = 4663            # Robinhood. 8453 base, 1 ethereum, 56 bsc, 42161 arbitrum
pool_source = "krystal" # krystal (any chain) | rhpools (chain-indexed, Robinhood only)
# rhpools_url = "https://rhpools.lol"   # or http://127.0.0.1:8196 for a local indexer
# rhpools_top = 150       # pools per window taken from rhpools (150 = one request each)
# rhpools_windows = []    # [] = 1h+24h on the public instance, all four on a local one
reconcile = false       # also fetch the other feed and show SRCΔ (Krystal vs chain), Robinhood only
quote = "USDG"          # only pools containing this token; "any" to disable
profile = "balanced"    # conservative | balanced | aggressive | degen
protocols = []          # e.g. ["uniswapv4", "ramsescl"]; empty = all
size = 50000            # your position size in USD for MY$/D, NET$/D, SHARE
wallet = ""             # 0x… for the positions view and monitoring (or KRYSTAL_WALLET)

refresh = 300           # TUI auto-refresh seconds, 0 = off
images = ""             # "" auto-detect | tgp | sixel | halfcell | unicode | off

interval = 300          # `watch` daemon seconds between ticks
telegram = false        # deliver alerts to Telegram (needs .env token + chat id)
# digest_hour = 0       # UTC hour to write + send the daily vault report

rotate_cost_pct = 0.3   # % of value assumed lost when rotating a position
snapshot_days = 14      # how long local pool history is kept

[alerts]
pos_pnl_drop = 0.05     # alert when a position loses this fraction of its value between ticks
edge_sigma = 0.5        # alert when the nearest range edge is closer than this many daily σ
watch_tvl_move = 30     # % TVL move in an hour on a starred pool
watch_fee_drop = -50    # % fee24 change on a starred pool
watch_drawdown = -30    # % drawdown on a starred pool
"""

ENV_TEMPLATE = """# secrets for krystal-curator — never commit this file
KRYSTAL_WALLET=0x
# KRYSTAL_CLOUD_KEY=            # optional, cloud.krystal.app (paid units)
# TELEGRAM_BOT_TOKEN=           # from @BotFather
# TELEGRAM_CHAT_ID=             # your user id or a group id
"""


def write_templates(directory: Path, *, force: bool = False) -> list[Path]:
    """Write config.toml and .env templates; returns the files created."""
    out: list[Path] = []
    for name, body in ((FILE_NAME, TEMPLATE), (".env", ENV_TEMPLATE)):
        p = directory / name
        if p.exists() and not force:
            continue
        p.write_text(body, encoding="utf-8")
        out.append(p)
    return out
