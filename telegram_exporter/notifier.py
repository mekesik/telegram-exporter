"""Telegram Bot API notifications about export progress.

The bot is only a notification channel: it reports what was downloaded and
what is still left. It never receives the Telegram account session and cannot
read chats on its own.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import urllib.parse
import urllib.request
from typing import Any, Callable

API_BASE = "https://api.telegram.org"


def escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


class BotNotifier:
    """Send HTML messages through the Telegram Bot API.

    ``transport`` is injectable for offline tests: it receives the text and
    returns ``True`` on success. Any failure is recorded in ``last_error`` and
    never raises into the exporter.
    """

    def __init__(
        self,
        token: str,
        chat_id: str | int,
        *,
        transport: Callable[[str], bool] | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.token = (token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.transport = transport
        self.timeout = timeout
        self.last_error: str | None = None
        self.sent = 0
        self.failed = 0

    @property
    def enabled(self) -> bool:
        return bool(self.transport is not None or (self.token and self.chat_id))

    async def send(self, text: str) -> bool:
        if not self.enabled or not (text or "").strip():
            return False
        if self.transport is not None:
            try:
                ok = bool(self.transport(text))
            except Exception as exc:  # noqa: BLE001 - notifications must not break export
                self.last_error = f"{type(exc).__name__}: {exc}"
                ok = False
        else:
            ok = await asyncio.to_thread(self._send_sync, text)

        if ok:
            self.sent += 1
        else:
            self.failed += 1
        return ok

    def _send_sync(self, text: str) -> bool:
        url = f"{API_BASE}/bot{self.token}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": self.chat_id,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"User-Agent": "Tgk-Alg0rithmX"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", "replace")
            data = json.loads(body)
            if not data.get("ok"):
                self.last_error = str(data.get("description") or "Telegram Bot API error")
                return False
            self.last_error = None
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False


def bot_settings(
    config: dict[str, Any] | None = None,
    token: str | None = None,
    chat_id: str | int | None = None,
) -> tuple[str | None, str | None]:
    """Resolve bot token and chat from CLI, environment or config."""
    config = config or {}
    resolved_token = (
        token
        or os.environ.get("TELEGRAM_BOT_TOKEN")
        or config.get("bot_token")
    )
    resolved_chat = (
        chat_id
        or os.environ.get("TELEGRAM_BOT_CHAT_ID")
        or config.get("bot_chat_id")
    )
    token_text = str(resolved_token).strip() if resolved_token else None
    chat_text = str(resolved_chat).strip() if resolved_chat else None
    return token_text or None, chat_text or None


def format_start(chats: list[str], *, queue_total: int) -> str:
    lines = [
        "🚀 <b>Экспорт запущен</b>",
        f"Чатов в очереди: <b>{queue_total}</b>",
    ]
    shown = [escape(title) for title in chats[:15]]
    if shown:
        lines.append("• " + "\n• ".join(shown))
    if len(chats) > len(shown):
        lines.append(f"…и ещё {len(chats) - len(shown)}")
    lines.append("")
    lines.append("Я буду писать, что скачано и сколько осталось.")
    return "\n".join(lines)


def format_progress(
    *,
    chat_title: str,
    done: int,
    total: int | None = None,
    media: int = 0,
    media_failed: int = 0,
    queue_left: int | None = None,
    new_only: bool = False,
    note: str | None = None,
) -> str:
    if new_only:
        lines = [f"📥 <b>{escape(chat_title)}</b>"]
        lines.append(f"Докачано новых сообщений: <b>{done}</b>")
    else:
        lines = [f"📥 <b>{escape(chat_title)}</b>"]
        if total is not None and total > 0:
            remaining = max(0, total - done)
            percent = min(100, int(done * 100 / total)) if total else 0
            lines.append(
                f"Скачано: <b>{done}</b> из <b>{total}</b> ({percent}%)"
            )
            lines.append(f"Осталось в чате: <b>{remaining}</b>")
        else:
            lines.append(f"Скачано сообщений: <b>{done}</b>")

    lines.append(f"Файлов скачано: <b>{media}</b>")
    if media_failed:
        lines.append(f"⚠️ Не удалось скачать файлов: <b>{media_failed}</b>")
    if queue_left:
        lines.append(f"Чатов после этого: <b>{queue_left}</b>")
    if note:
        lines.append(escape(note))
    return "\n".join(lines)


def format_finish(
    *,
    chats: int,
    messages: int,
    media: int,
    failures: int,
    seconds: float | None = None,
) -> str:
    lines = [
        "🏁 <b>Экспорт завершён</b>",
        f"Чатов: <b>{chats}</b>",
        f"Сообщений: <b>{messages}</b>",
        f"Файлов: <b>{media}</b>",
    ]
    if failures:
        lines.append(f"⚠️ Ошибок: <b>{failures}</b>")
    if seconds:
        minutes = int(seconds // 60)
        lines.append(f"Время: {minutes} мин {int(seconds % 60)} с")
    return "\n".join(lines)


def detect_chat_id(token: str, *, timeout: float = 15.0) -> str | None:
    """Return the chat id of the latest bot update (for ``bot`` setup)."""
    url = f"{API_BASE}/bot{token}/getUpdates?limit=100&timeout=0"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except Exception:
        return None
    if not data.get("ok"):
        return None
    for update in reversed(data.get("result") or []):
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            payload = update.get(key) or {}
            chat = payload.get("chat") or {}
            chat_id = chat.get("id")
            if chat_id is not None:
                return str(chat_id)
    return None
