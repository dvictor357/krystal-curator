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
class Agent:
    """Local-LLM addon (`agent/`): off unless `enabled`; nothing else changes without it.
    `base_url` set → attach to a running llama-server; empty → spawn one from `model`."""

    enabled: bool = False
    model: str = ""  # path to a GGUF, e.g. ~/.lmstudio/models/openbmb/MiniCPM5-2B-GGUF/…Q8_0.gguf
    base_url: str = ""  # e.g. http://127.0.0.1:8081 to reuse a server you started yourself
    llama_server: str = "llama-server"  # binary (Homebrew llama.cpp) when we spawn it
    port: int = 8081
    ctx: int = 16384  # context window; tool outputs are compacted to fit
    gpu_layers: int = 99
    max_steps: int = 8  # tool calls per task before the agent must answer
    timeout: float = 180.0  # seconds per model call
    temperature: float = 0.2
    max_tokens: int = 2000  # per step, reasoning included
    # thinking tokens per step. 0 = thinking off (`enable_thinking: false` per request,
    # verified on MiniCPM5). N > 0 = thinking on, capped by `--reasoning-budget N` on the
    # server we spawn (a per-request budget is not honoured by llama-server 0.4; on an
    # attached server start it with that flag yourself). Unlimited, a 2B model thinks its
    # whole `max_tokens` away and returns nothing (verified: 2,000 tokens, empty JSON).
    reasoning_budget: int = 0


@dataclass(slots=True)
class Config:
    chain: int = ROBINHOOD
    pool_source: str = "krystal"  # the only feed today; kept so a chain feed can plug in
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
    agent: Agent = field(default_factory=Agent)
    source: Path | None = None  # file it was loaded from, if any

    @property
    def quote_or_none(self) -> str | None:
        return None if self.quote.lower() in ("", "any") else self.quote

    @property
    def fetch_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for `api.fetch_pools` selecting the configured feed."""
        return {
            "source": self.pool_source,
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


def _coerce_agent(name: str, raw: Any) -> Any:
    kind = {f.name: f.type for f in fields(Agent)}[name]
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "bool":
        return str(raw).lower() in ("1", "true", "yes", "on")
    return os.path.expanduser(str(raw)) if name == "model" else str(raw)


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
            elif k == "agent" and isinstance(v, dict):
                for ak, av in v.items():
                    if hasattr(cfg.agent, ak):
                        setattr(cfg.agent, ak, _coerce_agent(ak, av))
            elif hasattr(cfg, k) and k not in ("source", "alerts", "agent"):
                setattr(cfg, k, _coerce(cfg, k, v))
        cfg.source = path
    for env, name in _ENV_MAP.items():
        if os.environ.get(env):
            setattr(cfg, name, _coerce(cfg, name, os.environ[env]))
    return cfg


TEMPLATE = """# krystal-curator configuration. Precedence: CLI flag > env var > this file > default.
# Secrets (KRYSTAL_CLOUD_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) go in .env, not here.

chain = 4663            # Robinhood. 8453 base, 1 ethereum, 56 bsc, 42161 arbitrum
pool_source = "krystal" # the only pool feed today
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

[agent]                 # local-LLM addon: reads reviews, calls our tools, never writes anything
enabled = false
model = ""              # GGUF path, e.g. "~/.lmstudio/models/openbmb/MiniCPM5-2B-GGUF/MiniCPM5-2B-Q8_0.gguf"
# base_url = ""         # "http://127.0.0.1:8081" to reuse a llama-server you run yourself
# llama_server = "llama-server"   # binary used when we spawn it (brew install llama.cpp)
# port = 8081
# ctx = 16384
# max_steps = 8         # tool calls per task
# timeout = 180         # seconds per model call
# reasoning_budget = 0  # 0 = thinking off; N = thinking capped at N tokens (spawned server only)
"""

ENV_TEMPLATE = """# secrets for krystal-curator — never commit this file
KRYSTAL_WALLET=0x
# KRYSTAL_CLOUD_KEY=            # optional, cloud.krystal.app (paid units)
# TELEGRAM_BOT_TOKEN=           # from @BotFather
# TELEGRAM_CHAT_ID=             # your user id or a group id
"""


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v) if isinstance(v, float) else str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, Path):
        v = str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump(cfg: Config) -> str:
    """The configuration as TOML: every top-level field, then `[alerts]` and `[agent]`.
    Comments from a hand-written file are not kept — `save` writes what the settings
    screen holds, nothing else."""
    lines = ["# krystal-curator configuration, written by the settings screen.", ""]
    for f in fields(Config):
        if f.name in ("source", "alerts", "agent"):
            continue
        v = getattr(cfg, f.name)
        if v is None:
            continue  # optional and unset (digest_hour)
        lines.append(f"{f.name} = {_toml_value(v)}")
    for table in ("alerts", "agent"):
        lines += ["", f"[{table}]"]
        sub = getattr(cfg, table)
        for f in fields(sub):
            lines.append(f"{f.name} = {_toml_value(getattr(sub, f.name))}")
    return "\n".join(lines) + "\n"


def save(cfg: Config, path: Path | None = None) -> Path:
    """Write `cfg` to `path`, else to the file it was loaded from, else `./config.toml`."""
    target = Path(path) if path else (cfg.source or Path.cwd() / FILE_NAME)
    target.write_text(dump(cfg), encoding="utf-8")
    cfg.source = target
    return target


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
