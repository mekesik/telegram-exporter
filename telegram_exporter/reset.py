"""Reset exported message/media payloads while retaining chat metadata and dates."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .render import render_chat_dir, write_root_index
from .utils import read_json, write_json


def reset_export(path: Path, *, confirmed: bool = False, input_fn=input) -> int:
    root = Path(path).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"Папка экспорта не найдена: {root}")
    chats = [p for p in root.iterdir() if p.is_dir() and (p / "chat.json").exists()]
    if not chats:
        raise ValueError(f"В {root} нет экспортированных чатов.")
    if not confirmed:
        answer = input_fn(f"Очистить сообщения и медиа в {len(chats)} чатах, сохранив даты и метаданные? [y/N] ")
        if answer.strip().casefold() not in {"y", "yes", "д", "да"}:
            print("Сброс отменён.")
            return 0

    for chat_dir in chats:
        chat = read_json(chat_dir / "chat.json") or {}
        for file in chat_dir.rglob("messages.*"):
            if file.is_file():
                file.unlink()
        media_dir = chat_dir / "media"
        if media_dir.exists():
            shutil.rmtree(media_dir)
        topics_file = chat_dir / "topics.json"
        topics_data = read_json(topics_file) or {}
        for topic in topics_data.get("topics", []):
            topic["count"] = 0
            topic["last_message_id"] = 0
            topic["last_date"] = None
        if topics_file.exists():
            write_json(topics_file, topics_data)
        state = read_json(chat_dir / "state.json") or {}
        for topic in state.get("topics", {}).values():
            topic["count"] = 0
            topic["last_message_id"] = 0
            topic["last_date"] = None
        state.update({"last_message_id": 0, "last_date": None})
        if state:
            write_json(chat_dir / "state.json", state)
        chat.update({"messages": 0, "media_files": 0, "last_message_id": 0})
        write_json(chat_dir / "chat.json", chat)

    manifest = read_json(root / "manifest.json") or {"chats": []}
    for entry in manifest.get("chats", []):
        entry["messages"] = 0
        entry["media_files"] = 0
    if manifest.get("chats"):
        write_json(root / "manifest.json", manifest)
        write_root_index(root, manifest)
    print(f"Сброшено чатов: {len(chats)}. Даты экспорта и метаданные сохранены.")
    return len(chats)
