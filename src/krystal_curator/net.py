"""One door for outbound HTTP: retry with backoff, and error text that carries no secret.

Every feed this tool talks to (Krystal, DexScreener, Telegram, rhpools) is a public
service that hiccups: 429s, 5xxs, dropped connections, slow reads. A daemon that alerts
on real capital must ride those out, not log a false "vaults: ConnectError" and skip a
tick. And when it does give up, the text that reaches a log, a TUI toast or a Telegram
reply must not contain the bot token (which Telegram puts in the URL) or the Cloud key.

`request()` is the only function call sites need. `register_secret()` teaches `redact()`
what to scrub; the Telegram and Cloud helpers register theirs when they read them.
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable, Iterable
from typing import Any

import httpx

log = logging.getLogger("krystal.http")

RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
MAX_BACKOFF_S = 10.0
MAX_RETRY_AFTER_S = 30.0

_SECRETS: set[str] = set()
_MIN_SECRET_LEN = 8  # shorter values would redact ordinary words
# Telegram bot tokens live in the URL path; scrub the shape even if unregistered.
_TG_TOKEN_RE = re.compile(r"/bot\d{6,}:[A-Za-z0-9_-]{20,}")


class _RedactingFilter(logging.Filter):
    """Scrub secrets from any record on the loggers it is attached to (httpx logs URLs)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.getMessage()))
        record.args = ()
        return True


for _name in ("httpx", "httpcore", "krystal.http"):
    logging.getLogger(_name).addFilter(_RedactingFilter())


class HttpError(RuntimeError):
    """A request that failed after its retries. `str()` is safe to show anywhere."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def register_secret(value: str | None) -> None:
    if value and len(value) >= _MIN_SECRET_LEN:
        _SECRETS.add(value)


def redact(text: str) -> str:
    """Replace every registered secret (and any bot-token-shaped path) with a marker."""
    out = _TG_TOKEN_RE.sub("/bot<redacted>", text)
    for s in sorted(_SECRETS, key=len, reverse=True):  # longest first: no partial leaks
        out = out.replace(s, "<redacted>")
    return out


def _retry_after(r: httpx.Response) -> float | None:
    raw = r.headers.get("retry-after")
    if not raw:
        return None
    try:
        return min(float(raw), MAX_RETRY_AFTER_S)
    except ValueError:
        return None  # HTTP-date form: rare from these APIs, treat as absent


def _is_idempotent(method: str) -> bool:
    return method.upper() in ("GET", "HEAD", "OPTIONS")


def request(
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 0.5,
    retry_statuses: Iterable[int] = RETRY_STATUSES,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    **kw: Any,
) -> httpx.Response:
    """`httpx.request` with retries; raises HttpError (redacted) instead of httpx errors.

    Retries transport failures and `retry_statuses` up to `retries` times with
    exponential backoff + jitter, honouring Retry-After. A non-idempotent method
    (POST…) is retried only when the request provably never reached the server
    (connect failures) or the server said so (429/503 with a status); a read timeout
    on a POST is ambiguous and is not retried — a lost alert beats a duplicate one
    being sent three times. Responses with other status codes are returned as-is;
    call `raise_for_status()` if you want them fatal.
    """
    statuses = frozenset(retry_statuses)
    rng = rng or random.Random()
    send = client.request if client is not None else httpx.request
    attempt = 0
    while True:
        try:
            r = send(method, url, **kw)
        except httpx.HTTPError as e:
            safe_reason = redact(f"{type(e).__name__}: {e}")
            ambiguous = not _is_idempotent(method) and not isinstance(
                e, httpx.ConnectError | httpx.ConnectTimeout
            )
            if attempt >= retries or ambiguous:
                raise HttpError(f"{method} {redact(url)}: {safe_reason}") from None
            delay = None
        else:
            if r.status_code not in statuses or attempt >= retries:
                return r
            safe_reason = f"HTTP {r.status_code}"
            delay = _retry_after(r)
        if delay is None:
            delay = min(backoff * 2**attempt, MAX_BACKOFF_S) + rng.uniform(0, backoff)
        attempt += 1
        log.warning(
            "%s %s: %s; retry %d/%d in %.1fs",
            method,
            redact(url),
            safe_reason,
            attempt,
            retries,
            delay,
        )
        sleep(delay)


def get(url: str, **kw: Any) -> httpx.Response:
    return request("GET", url, **kw)


def post(url: str, **kw: Any) -> httpx.Response:
    return request("POST", url, **kw)


def status_error(r: httpx.Response, what: str) -> HttpError:
    """HttpError for a non-2xx response, without the URL's secrets."""
    return HttpError(
        f"{what}: HTTP {r.status_code} from {redact(str(r.request.url))}", status=r.status_code
    )
