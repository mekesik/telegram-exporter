"""Streaming JSONL storage with a small LRU pool of open files."""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


class JsonlWriter:
    def __init__(self, path: Path, append: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.handle = path.open("a" if append else "w", encoding="utf-8", newline="\n")
        self.written = 0

    def write(self, data: dict[str, Any]) -> None:
        self.handle.write(json.dumps(data, ensure_ascii=False))
        self.handle.write("\n")
        self.written += 1
        if self.written % 10 == 0:
            self.handle.flush()

    def close(self) -> None:
        if not self.handle.closed:
            self.handle.flush()
            self.handle.close()


class WriterPool:
    """One messages.jsonl per forum topic, with an LRU limit on open files."""

    def __init__(self, chat_dir: Path, append: bool, max_open: int = 48) -> None:
        self.chat_dir = Path(chat_dir)
        self.append = append
        self.max_open = max_open
        self._open: OrderedDict[int | None, JsonlWriter] = OrderedDict()
        self._opened_once: set[int | None] = set()
        self.stats: dict[int | None, dict[str, Any]] = {}

    def _path_for(self, rel_dir: str | None) -> Path:
        if rel_dir:
            return self.chat_dir / rel_dir / "messages.jsonl"
        return self.chat_dir / "messages.jsonl"

    def _ensure_stat(self, topic_id: int | None, title: str | None, rel_dir: str | None) -> dict[str, Any]:
        return self.stats.setdefault(
            topic_id,
            {"count": 0, "max_id": 0, "min_id": 0,
             "first_date": None, "last_date": None,
             "title": title, "dir": rel_dir},
        )

    def _open_writer(self, topic_id: int | None, rel_dir: str | None) -> JsonlWriter:
        if len(self._open) >= self.max_open:
            _, writer = self._open.popitem(last=False)
            writer.close()
        path = self._path_for(rel_dir)
        # A full export truncates the file on the first open; LRU re-opens and
        # incremental exports append.
        append = self.append or topic_id in self._opened_once
        writer = JsonlWriter(path, append=append)
        self._opened_once.add(topic_id)
        self._open[topic_id] = writer
        return writer

    def write(
        self,
        topic_id: int | None,
        rel_dir: str | None,
        title: str | None,
        data: dict[str, Any],
    ) -> None:
        writer = self._open.get(topic_id)
        if writer is None:
            writer = self._open_writer(topic_id, rel_dir)
        else:
            self._open.move_to_end(topic_id)
        writer.write(data)

        stat = self._ensure_stat(topic_id, title, rel_dir)
        stat["count"] += 1
        message_id = int(data.get("id") or 0)
        date = data.get("date")
        stat["max_id"] = max(stat["max_id"], message_id)
        stat["min_id"] = min(stat["min_id"], message_id) if stat["min_id"] else message_id
        if date:
            if stat["first_date"] is None:
                stat["first_date"] = date
            stat["last_date"] = date
        if title and not stat.get("title"):
            stat["title"] = title

    def close(self) -> None:
        for writer in self._open.values():
            writer.close()
        self._open.clear()

    def __enter__(self) -> "WriterPool":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
