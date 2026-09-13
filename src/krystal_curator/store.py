"""Local sqlite store: pool snapshots per refresh + watchlist."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

from .models import Pool

_DB = Path(user_data_dir("krystal-curator")) / "curator.sqlite3"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    ts        INTEGER NOT NULL,
    chain_id  INTEGER NOT NULL,
    address   TEXT    NOT NULL,
    protocol  TEXT    NOT NULL,
    tvl       REAL, vol24 REAL, fee24 REAL, vol1h REAL, fee1h REAL,
    fee7d     REAL, apr24 REAL, volatility REAL, drawdown REAL
);
CREATE INDEX IF NOT EXISTS snap_pool_ts ON snapshots (chain_id, address, protocol, ts);
CREATE TABLE IF NOT EXISTS vault_snapshots (
    ts        INTEGER NOT NULL,
    chain_id  INTEGER NOT NULL,
    address   TEXT    NOT NULL,
    tvl       REAL, pnl REAL, earning24h REAL, my_value REAL, idle REAL, open_n INTEGER
);
CREATE INDEX IF NOT EXISTS vsnap_ts ON vault_snapshots (chain_id, address, ts);
CREATE TABLE IF NOT EXISTS watchlist (
    chain_id  INTEGER NOT NULL,
    address   TEXT    NOT NULL,
    protocol  TEXT    NOT NULL,
    pair      TEXT,
    added_ts  INTEGER NOT NULL,
    PRIMARY KEY (chain_id, address, protocol)
);
"""


@dataclass(slots=True, frozen=True)
class Point:
    ts: int
    tvl: float
    vol24: float
    fee24: float
    volatility: float
    drawdown: float

    @property
    def fee_yield(self) -> float:
        return self.fee24 / self.tvl if self.tvl > 0 else 0.0


@dataclass(slots=True, frozen=True)
class VaultPoint:
    ts: int
    tvl: float
    pnl: float
    earning24h: float
    my_value: float
    idle: float
    open_n: int


@dataclass(slots=True, frozen=True)
class Delta:
    """Change vs the snapshot closest to `hours` ago (None if no history)."""

    hours: float | None
    tvl_pct: float | None
    fee24_pct: float | None
    vol24_pct: float | None


def _pct(now: float, then: float) -> float | None:
    return (now - then) / then * 100 if then > 0 else None


class Store:
    def __init__(self, path: Path = _DB) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._lock = threading.Lock()
        self.watch: set[tuple[int, str, str]] = set(self._load_watch())

    # ---- snapshots ----------------------------------------------------
    def last_ts(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT MAX(ts) FROM snapshots").fetchone()
        return int(row[0] or 0)

    def record(self, pools: list[Pool], ts: int | None = None) -> int:
        ts = ts or int(time.time())
        rows = [
            (
                ts,
                p.chain_id,
                p.address,
                p.protocol,
                p.tvl,
                p.s24h.volume,
                p.s24h.fee,
                p.s1h.volume,
                p.s1h.fee,
                p.s7d.fee,
                p.s24h.apr,
                p.volatility,
                p.drawdown24h,
            )
            for p in pools
        ]
        with self._lock:
            self._db.executemany("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            self._db.commit()
        return len(rows)

    def all_snapshots(self, days: float = 14) -> list[tuple]:
        """(ts, chain_id, address, protocol, tvl, vol24, fee24, vol1h, fee1h, fee7d, apr24,
        volatility, drawdown) for every snapshot in the window, oldest first."""
        since = int(time.time() - days * 86400)
        with self._lock:
            cur = self._db.execute(
                "SELECT ts, chain_id, address, protocol, tvl, vol24, fee24, vol1h, fee1h, fee7d, "
                "apr24, volatility, drawdown FROM snapshots WHERE ts >= ? ORDER BY ts",
                (since,),
            )
            return cur.fetchall()

    def prune(self, keep_days: int = 30) -> None:
        cutoff = int(time.time()) - keep_days * 86400
        with self._lock:
            self._db.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
            self._db.commit()

    def history(self, p: Pool, *, hours: float = 48, limit: int = 200) -> list[Point]:
        since = int(time.time() - hours * 3600)
        with self._lock:
            cur = self._db.execute(
                "SELECT ts, tvl, vol24, fee24, volatility, drawdown FROM snapshots "
                "WHERE chain_id=? AND address=? AND protocol=? AND ts>=? ORDER BY ts DESC LIMIT ?",
                (p.chain_id, p.address, p.protocol, since, limit),
            )
            rows = cur.fetchall()
        return [Point(*r) for r in reversed(rows)]

    def delta(self, p: Pool, *, hours: float = 24) -> Delta:
        """Compare the pool now against the snapshot nearest to `hours` ago.

        Falls back to the oldest snapshot if history is shorter than `hours`.
        The very latest snapshot is skipped so a fresh refresh never compares to itself.
        """
        target = int(time.time() - hours * 3600)
        with self._lock:
            cur = self._db.execute(
                "SELECT ts, tvl, vol24, fee24 FROM snapshots "
                "WHERE chain_id=? AND address=? AND protocol=? "
                "ORDER BY ABS(ts - ?) LIMIT 2",
                (p.chain_id, p.address, p.protocol, target),
            )
            rows = cur.fetchall()
        if not rows:
            return Delta(None, None, None, None)
        # skip a row taken in the last 60s (that is the current refresh)
        fresh = int(time.time()) - 60
        rows = [r for r in rows if r[0] < fresh] or rows
        ts, tvl, vol24, fee24 = rows[0]
        age_h = (time.time() - ts) / 3600
        return Delta(
            hours=age_h,
            tvl_pct=_pct(p.tvl, tvl),
            fee24_pct=_pct(p.s24h.fee, fee24),
            vol24_pct=_pct(p.s24h.volume, vol24),
        )

    # ---- vault equity -------------------------------------------------
    def record_vaults(
        self, rows: list[tuple[int, str, float, float, float, float, float, int]]
    ) -> None:
        """rows: (chain_id, address, tvl, pnl, earning24h, my_value, idle, open_n)."""
        ts = int(time.time())
        with self._lock:
            self._db.executemany(
                "INSERT INTO vault_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
                [(ts, *r) for r in rows],
            )
            self._db.commit()

    def last_vault_ts(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT MAX(ts) FROM vault_snapshots").fetchone()
        return int(row[0] or 0)

    def vault_history(
        self, chain_id: int, address: str, *, days: float = 30, limit: int = 500
    ) -> list[VaultPoint]:
        since = int(time.time() - days * 86400)
        with self._lock:
            cur = self._db.execute(
                "SELECT ts, tvl, pnl, earning24h, my_value, idle, open_n FROM vault_snapshots "
                "WHERE chain_id=? AND address=? AND ts>=? ORDER BY ts DESC LIMIT ?",
                (chain_id, address, since, limit),
            )
            rows = cur.fetchall()
        return [VaultPoint(*r) for r in reversed(rows)]

    # ---- watchlist ----------------------------------------------------
    def _load_watch(self) -> list[tuple[int, str, str]]:
        cur = self._db.execute("SELECT chain_id, address, protocol FROM watchlist")
        return [(int(c), a, pr) for c, a, pr in cur.fetchall()]

    def is_watched(self, p: Pool) -> bool:
        return (p.chain_id, p.address, p.protocol) in self.watch

    def toggle_watch(self, p: Pool) -> bool:
        key = (p.chain_id, p.address, p.protocol)
        with self._lock:
            if key in self.watch:
                self._db.execute(
                    "DELETE FROM watchlist WHERE chain_id=? AND address=? AND protocol=?", key
                )
                self.watch.discard(key)
                on = False
            else:
                self._db.execute(
                    "INSERT OR REPLACE INTO watchlist VALUES (?,?,?,?,?)",
                    (*key, p.pair, int(time.time())),
                )
                self.watch.add(key)
                on = True
            self._db.commit()
        return on


def sparkline(values: list[float], width: int = 12) -> str:
    """▁▂▃▄▅▆▇█ over the last `width` values, scaled to their own min/max."""
    if not values:
        return ""
    vals = values[-width:]
    lo, hi = min(vals), max(vals)
    blocks = "▁▂▃▄▅▆▇█"
    if hi - lo < 1e-12:
        return blocks[3] * len(vals)
    return "".join(blocks[int((v - lo) / (hi - lo) * 7 + 0.5)] for v in vals)
