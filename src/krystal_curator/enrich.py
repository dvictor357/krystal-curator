"""Token metadata (logo, website, socials) from DexScreener, with caching.

Krystal's own token endpoint returns empty `links` for Robinhood tokens, so
DexScreener is the source: https://api.dexscreener.com/tokens/v1/{chain}/{addr,...}
(no key, 300 req/min, up to 30 addresses per call).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from platformdirs import user_cache_dir

DEXSCREENER_TOKENS = "https://api.dexscreener.com/tokens/v1"

# Krystal chainId -> DexScreener chain slug
DEX_CHAIN: dict[int, str] = {
    1: "ethereum",
    10: "optimism",
    56: "bsc",
    137: "polygon",
    999: "hyperevm",
    2020: "ronin",
    4663: "robinhood",
    8453: "base",
    42161: "arbitrum",
    43114: "avalanche",
}

_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 krystal-curator/0.1"}
_CACHE_DIR = Path(user_cache_dir("krystal-curator"))
_META_TTL = 6 * 3600


@dataclass(slots=True)
class TokenInfo:
    address: str
    symbol: str = ""
    name: str = ""
    image_url: str = ""
    website: str = ""
    twitter: str = ""
    telegram: str = ""
    discord: str = ""
    other: list[tuple[str, str]] = field(default_factory=list)  # (label, url)
    fetched_at: float = 0.0

    @property
    def links(self) -> list[tuple[str, str]]:
        out = [
            (k, v)
            for k, v in (
                ("WEB", self.website),
                ("X", self.twitter),
                ("TG", self.telegram),
                ("DC", self.discord),
            )
            if v
        ]
        return out + self.other

    def to_json(self) -> dict:
        return {
            "address": self.address,
            "symbol": self.symbol,
            "name": self.name,
            "image_url": self.image_url,
            "website": self.website,
            "twitter": self.twitter,
            "telegram": self.telegram,
            "discord": self.discord,
            "other": self.other,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_json(cls, d: dict) -> TokenInfo:
        return cls(**{**d, "other": [tuple(x) for x in d.get("other", [])]})


class TokenMeta:
    """Thread-safe memo of TokenInfo per (chain, address) + logo bytes on disk."""

    def __init__(self, cache_dir: Path = _CACHE_DIR) -> None:
        self._dir = cache_dir
        self._meta: dict[str, TokenInfo] = {}
        self._lock = threading.Lock()
        (self._dir / "logos").mkdir(parents=True, exist_ok=True)
        self._meta_file = self._dir / "tokens.json"
        self._load()

    # ---- persistence --------------------------------------------------
    def _load(self) -> None:
        try:
            raw = json.loads(self._meta_file.read_text())
            self._meta = {k: TokenInfo.from_json(v) for k, v in raw.items()}
        except (OSError, ValueError, TypeError):
            self._meta = {}

    def _save(self) -> None:
        try:
            self._meta_file.write_text(json.dumps({k: v.to_json() for k, v in self._meta.items()}))
        except OSError:
            pass

    @staticmethod
    def _key(chain_id: int, address: str) -> str:
        return f"{chain_id}:{address.lower()}"

    # ---- metadata -----------------------------------------------------
    def get(self, chain_id: int, address: str) -> TokenInfo | None:
        return self._meta.get(self._key(chain_id, address))

    def fetch(self, chain_id: int, addresses: list[str]) -> dict[str, TokenInfo]:
        """Return TokenInfo for each address (cache first; fetch the rest in one call)."""
        now = time.time()
        out: dict[str, TokenInfo] = {}
        missing: list[str] = []
        with self._lock:
            for a in addresses:
                info = self._meta.get(self._key(chain_id, a))
                if info and now - info.fetched_at < _META_TTL:
                    out[a.lower()] = info
                else:
                    missing.append(a.lower())
        slug = DEX_CHAIN.get(chain_id)
        if missing and slug:
            fetched = _dexscreener(slug, missing)
            with self._lock:
                for a in missing:
                    info = fetched.get(a) or TokenInfo(address=a, fetched_at=now)
                    info.fetched_at = now
                    self._meta[self._key(chain_id, a)] = info
                    out[a] = info
                self._save()
        return out

    # ---- logos --------------------------------------------------------
    def logo_path(self, url: str) -> Path | None:
        """Download (once) and return the local file for a logo URL."""
        if not url:
            return None
        name = hashlib.sha1(url.encode()).hexdigest()[:24]
        path = self._dir / "logos" / name
        if path.exists() and path.stat().st_size > 0:
            return path
        try:
            r = httpx.get(url, headers=_HEADERS, timeout=15, follow_redirects=True)
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("image/"):
                return None
            path.write_bytes(r.content)
            return path
        except (httpx.HTTPError, OSError):
            return None


def _dexscreener(slug: str, addresses: list[str]) -> dict[str, TokenInfo]:
    out: dict[str, TokenInfo] = {}
    for i in range(0, len(addresses), 30):
        chunk = addresses[i : i + 30]
        try:
            r = httpx.get(
                f"{DEXSCREENER_TOKENS}/{slug}/{','.join(chunk)}", headers=_HEADERS, timeout=20
            )
            r.raise_for_status()
            pairs = r.json()
        except (httpx.HTTPError, ValueError):
            continue
        if not isinstance(pairs, list):
            continue
        # Many pairs per token; take the first that carries `info`, else any.
        for pair in pairs:
            base = pair.get("baseToken") or {}
            addr = (base.get("address") or "").lower()
            if addr not in chunk:
                continue
            info = pair.get("info") or {}
            cur = out.get(addr)
            if cur and cur.image_url:
                continue
            ti = cur or TokenInfo(address=addr)
            ti.symbol = base.get("symbol") or ti.symbol
            ti.name = base.get("name") or ti.name
            ti.image_url = info.get("imageUrl") or ti.image_url
            for w in info.get("websites") or []:
                url = w.get("url") or ""
                if url and not ti.website:
                    ti.website = url
                elif url:
                    ti.other.append(((w.get("label") or "WEB").upper()[:8], url))
            for s in info.get("socials") or []:
                t, url = (s.get("type") or "").lower(), s.get("url") or ""
                if not url:
                    continue
                if t == "twitter":
                    ti.twitter = ti.twitter or url
                elif t == "telegram":
                    ti.telegram = ti.telegram or url
                elif t == "discord":
                    ti.discord = ti.discord or url
                else:
                    ti.other.append((t.upper()[:8], url))
            out[addr] = ti
    return out
