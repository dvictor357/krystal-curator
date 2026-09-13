"""Outbound notifications: Telegram bot (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)."""

from __future__ import annotations

import os
from pathlib import Path

import httpx

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ENV = "TELEGRAM_CHAT_ID"
_MAX = 4000  # Telegram hard limit is 4096 chars per message


class Telegram:
    def __init__(self, token: str, chat_id: str) -> None:
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id

    @classmethod
    def from_env(cls) -> Telegram | None:
        token, chat = os.environ.get(TOKEN_ENV), os.environ.get(CHAT_ENV)
        return cls(token, chat) if token and chat else None

    def send(self, text: str, *, html: bool = False) -> bool:
        ok = True
        for i in range(0, max(len(text), 1), _MAX):
            chunk = text[i : i + _MAX]
            payload: dict = {
                "chat_id": self.chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if html:
                payload["parse_mode"] = "HTML"
            try:
                r = httpx.post(f"{self.base}/sendMessage", json=payload, timeout=20)
                ok &= r.status_code == 200
            except httpx.HTTPError:
                ok = False
        return ok

    def get_updates(self, offset: int | None, timeout: int = 0) -> list[dict]:
        """Long-poll incoming messages; returns raw update objects (may be empty)."""
        params: dict = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        try:
            r = httpx.get(f"{self.base}/getUpdates", params=params, timeout=timeout + 10)
            if r.status_code != 200:
                return []
            return (r.json() or {}).get("result") or []
        except (httpx.HTTPError, ValueError):
            return []

    def set_commands(self, commands: list[tuple[str, str]]) -> bool:
        try:
            r = httpx.post(
                f"{self.base}/setMyCommands",
                json={"commands": [{"command": c, "description": d} for c, d in commands]},
                timeout=15,
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def send_file(self, path: Path, caption: str = "") -> bool:
        try:
            with path.open("rb") as f:
                r = httpx.post(
                    f"{self.base}/sendDocument",
                    data={"chat_id": self.chat_id, "caption": caption[:1000]},
                    files={"document": (path.name, f, "text/markdown")},
                    timeout=60,
                )
            return r.status_code == 200
        except (httpx.HTTPError, OSError):
            return False

    def whoami(self) -> str | None:
        """Bot username if the token works, else None."""
        try:
            r = httpx.get(f"{self.base}/getMe", timeout=15)
            return (r.json().get("result") or {}).get("username") if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None
