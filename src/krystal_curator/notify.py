"""Outbound notifications: Telegram bot (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from . import net

log = logging.getLogger("krystal.telegram")
TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ENV = "TELEGRAM_CHAT_ID"
_MAX = 4000  # Telegram hard limit is 4096 chars per message


class Telegram:
    def __init__(self, token: str, chat_id: str) -> None:
        net.register_secret(token)  # Telegram puts it in the URL: redact everywhere
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id

    def _call(self, method: str, *, timeout: float, retries: int = 2, **kw) -> dict | None:
        """One Bot API call; the parsed body on 200, else None (already logged, redacted)."""
        try:
            r = net.post(f"{self.base}/{method}", timeout=timeout, retries=retries, **kw)
        except net.HttpError as e:
            log.warning("telegram %s: %s", method, e)
            return None
        if r.status_code != 200:
            log.warning("telegram %s: HTTP %s %s", method, r.status_code, net.redact(r.text[:200]))
            return None
        try:
            return r.json()
        except ValueError:
            return None

    @classmethod
    def from_env(cls) -> Telegram | None:
        token, chat = os.environ.get(TOKEN_ENV), os.environ.get(CHAT_ENV)
        return cls(token, chat) if token and chat else None

    def send(self, text: str, *, html: bool = False, reply_markup: dict | None = None) -> bool:
        ok = True
        chunks = [text[i : i + _MAX] for i in range(0, max(len(text), 1), _MAX)]
        for n, chunk in enumerate(chunks):
            payload: dict = {
                "chat_id": self.chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if html:
                payload["parse_mode"] = "HTML"
            if reply_markup and n == len(chunks) - 1:
                payload["reply_markup"] = reply_markup
            ok &= self._call("sendMessage", json=payload, timeout=20) is not None
        return ok

    def get_updates(self, offset: int | None, timeout: int = 0) -> list[dict]:
        """Long-poll incoming messages; returns raw update objects (may be empty)."""
        params: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        # long poll: a read timeout here is normal-ish, so no retry beyond connect errors
        body = self._call("getUpdates", json=params, timeout=timeout + 10, retries=1)
        return (body or {}).get("result") or []

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._call(
            "answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text[:200]},
            timeout=10,
            retries=0,
        )

    def set_commands(self, commands: list[tuple[str, str]]) -> bool:
        body = self._call(
            "setMyCommands",
            json={"commands": [{"command": c, "description": d} for c, d in commands]},
            timeout=15,
        )
        return body is not None

    def send_file(self, path: Path, caption: str = "") -> bool:
        try:
            with path.open("rb") as f:
                body = self._call(
                    "sendDocument",
                    data={"chat_id": self.chat_id, "caption": caption[:1000]},
                    files={"document": (path.name, f, "text/markdown")},
                    timeout=60,
                    retries=0,  # a file handle cannot be re-read by a retry
                )
            return body is not None
        except OSError:
            return False

    def whoami(self) -> str | None:
        """Bot username if the token works, else None."""
        body = self._call("getMe", timeout=15)
        return ((body or {}).get("result") or {}).get("username")
