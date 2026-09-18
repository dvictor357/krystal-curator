"""Per-key stale-while-revalidate cache shared by the web API and the alert loop."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock, Thread

from fastapi import HTTPException, Response

from . import api


@dataclass
class Entry:
    at: float
    value: object
    upstream_ms: float
    error: str = ""


class Cache:
    """Per-key stale-while-revalidate: fresh → serve; stale → serve and refresh in the
    background; missing (or `fresh=True`) → fetch under that key's lock. One upstream call
    per key at a time regardless of how many users ask; `Meta` tells the client which path.
    """

    def __init__(self, capacity: int = 64):
        self.entries: OrderedDict[tuple, Entry] = OrderedDict()
        self.locks: dict[tuple, Lock] = {}
        self.refreshing: set[tuple] = set()
        self.guard = Lock()
        self.capacity = capacity

    def _lock(self, key: tuple) -> Lock:
        with self.guard:
            return self.locks.setdefault(key, Lock())

    def _load(self, key: tuple, fetch) -> Entry:
        started = time.perf_counter()
        try:
            value = fetch()
        except api.KrystalError as e:
            raise HTTPException(502, "Data provider unavailable. Try again shortly.") from e
        entry = Entry(time.time(), value, (time.perf_counter() - started) * 1000)
        with self.guard:
            self.entries[key] = entry
            self.entries.move_to_end(key)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
        return entry

    def _refresh(self, key: tuple, fetch):
        try:
            with self._lock(key):
                self._load(key, fetch)
        except HTTPException:
            pass  # stale copy stays; the next request tries again
        finally:
            with self.guard:
                self.refreshing.discard(key)

    def get(self, key: tuple, fetch, ttl: int = 90, stale: int = 600, fresh: bool = False):
        with self.guard:
            entry = self.entries.get(key)
        age = time.time() - entry.at if entry else None
        if entry and not fresh and age < ttl:
            return entry, Meta("hit", age, 0.0)
        if entry and not fresh and age < stale:
            with self.guard:
                spawn = key not in self.refreshing
                self.refreshing.add(key)
            if spawn:
                Thread(target=self._refresh, args=(key, fetch), daemon=True).start()
            return entry, Meta("stale", age, 0.0)
        with self._lock(key):
            with self.guard:
                entry = self.entries.get(key)
            if entry and not fresh and time.time() - entry.at < ttl:
                return entry, Meta(
                    "hit", time.time() - entry.at, 0.0
                )  # another request just loaded it
            entry = self._load(key, fetch)
        return entry, Meta("miss", 0.0, entry.upstream_ms)


@dataclass
class Meta:
    cache: str  # hit | stale | miss
    age: float
    upstream_ms: float

    def apply(self, response: Response, ttl: int):
        response.headers["X-Cache"] = self.cache
        response.headers["X-Upstream-Ms"] = f"{self.upstream_ms:.0f}"
        response.headers["X-Data-Age"] = f"{self.age:.0f}"
        response.headers["Cache-Control"] = f"private, max-age={ttl}"
