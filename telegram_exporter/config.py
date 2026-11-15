"""Config, credentials and session paths."""

from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Any

from .utils import ensure_dir, read_json, write_json

APP_NAME = "telegram-exporter"
APP_VERSION = "1.0.0"


def app_dir() -> Path:
    override = os.environ.get("TELEGRAM_EXPORTER_HOME")
    return Path(override).expanduser() if override else Path.home() / ".telegram_exporter"


def config_path() -> Path:
    return app_dir() / "config.json"


def sessions_dir() -> Path:
    return ensure_dir(app_dir() / "sessions")


def load_config() -> dict[str, Any]:
    return read_json(config_path()) or {}


def save_config(data: dict[str, Any]) -> None:
    current = load_config()
    current.update(data)
    write_json(config_path(), current)


def resolve_session_path(value: str | None, config: dict[str, Any] | None = None) -> str:
    """Return a Telethon session base path (Telethon adds ``.session``)."""
    config = config or {}
    value = (value or config.get("session") or "default").strip()
    path = Path(value).expanduser()

    looks_like_path = (
        path.is_absolute()
        or len(path.parts) > 1
        or value.lower().endswith(".session")
        or "/" in value
        or "\\" in value
    )
    if path.suffix.lower() == ".session":
        path = path.with_suffix("")

    if not looks_like_path:
        path = sessions_dir() / path

    ensure_dir(path.parent)
    return str(path)


def resolve_credentials(
    api_id: int | None = None,
    api_hash: str | None = None,
    *,
    interactive: bool = True,
) -> tuple[int, str]:
    """Get api_id/api_hash from CLI, env or config, prompting once if needed."""
    config = load_config()
    resolved_id = api_id or os.environ.get("TELEGRAM_API_ID") or config.get("api_id")
    resolved_hash = api_hash or os.environ.get("TELEGRAM_API_HASH") or config.get("api_hash")

    if resolved_id and resolved_hash:
        try:
            return int(resolved_id), str(resolved_hash)
        except (TypeError, ValueError):
            raise SystemExit("api_id должен быть числом. Проверьте config.json или --api-id.")

    if not interactive:
        raise SystemExit(
            "Не заданы api_id/api_hash.\n"
            "Укажите их через --api-id/--api-hash, переменные окружения "
            "TELEGRAM_API_ID/TELEGRAM_API_HASH или выполните `login`."
        )

    print()
    print("Нужны api_id и api_hash вашего Telegram-приложения.")
    print("1) Откройте https://my.telegram.org и войдите своим номером.")
    print("2) API development tools -> создайте приложение (название любое).")
    print("3) Скопируйте api_id и api_hash.")
    print()
    while True:
        raw_id = input("api_id: ").strip()
        raw_hash = input("api_hash: ").strip()
        try:
            resolved_id = int(raw_id)
        except ValueError:
            print("api_id должен быть числом, попробуйте снова.")
            continue
        if len(raw_hash) < 16:
            print("api_hash выглядит слишком коротким, попробуйте снова.")
            continue
        break

    save_config({"api_id": int(resolved_id), "api_hash": raw_hash})
    print(f"Сохранено в {config_path()}")
    return int(resolved_id), raw_hash


def read_password(prompt: str = "Пароль двухфакторной аутентификации: ") -> str:
    return getpass.getpass(prompt)
