"""Core export orchestration."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from telethon.tl import types

from .client import Resolver
from .media import download_media_file, plan_media
from .models import (
    build_chat_meta,
    build_topic_meta,
    message_to_dict,
)
from .notifier import (
    BotNotifier,
    escape,
    format_finish,
    format_progress,
    format_start,
)
from .progress import Progress
from .render import render_chat_dir, update_manifest
from .storage import WriterPool
from .utils import format_datetime, iso_now, read_json, slugify, write_json


def topic_dirname(topic_id: int, title: str | None) -> str:
    return f"topics/{int(topic_id):04d}_{slugify(title or f'Тема {topic_id}', 40)}"


def message_topic_id(message: Any) -> int:
    """Forum topic id for a message. General topic is 1."""
    action = getattr(message, "action", None)
    if isinstance(action, types.MessageActionTopicCreate):
        return int(message.id)

    reply = getattr(message, "reply_to", None)
    if reply is not None:
        top_id = getattr(reply, "reply_to_top_id", None)
        if top_id:
            return int(top_id)
        if getattr(reply, "forum_topic", False):
            msg_id = getattr(reply, "reply_to_msg_id", None)
            if msg_id:
                return int(msg_id)
    return 1


class Exporter:
    def __init__(
        self,
        client: Any,
        resolver: Resolver,
        out_root: Path,
        *,
        formats: set[str],
        download_media: bool = True,
        media_types: set[str] | None = None,
        max_media_size: int = 0,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        incremental: bool = False,
        split_topics: bool = True,
        wait_time: float | None = None,
        include_raw: bool = False,
        quiet: bool = False,
        notifier: BotNotifier | None = None,
        bot_every: float = 60.0,
    ) -> None:
        self.client = client
        self.resolver = resolver
        self.out_root = Path(out_root)
        self.formats = set(formats)
        self.download_media = download_media
        self.media_types = set(media_types or [])
        self.max_media_size = max(0, int(max_media_size))
        self.since = since
        self.until = until
        self.limit = limit
        self.incremental = incremental
        self.split_topics = split_topics
        self.wait_time = wait_time
        self.include_raw = include_raw
        self.quiet = quiet
        self.notifier = notifier
        self.bot_every = max(0.0, float(bot_every or 0))
        self.progress = Progress(enabled=not quiet)
        self.failures = 0
        self.fetched_total = 0
        self.media_total = 0
        self._chat_total: int | None = None
        self._queue_left = 0
        self._last_bot_time = 0.0
        self._bot_warned = False

    def log(self, text: str = "") -> None:
        if self.quiet:
            return
        self.progress.line(text)

    async def _notify(self, text: str | None) -> None:
        """Send a bot message; notifications must never break the export."""
        if self.notifier is None or not text:
            return
        try:
            await self.notifier.send(text)
        except Exception as exc:  # noqa: BLE001
            self.notifier.last_error = f"{type(exc).__name__}: {exc}"
        if self.notifier.last_error and not self._bot_warned:
            self._bot_warned = True
            self.log(f"[!] Бот-уведомления не отправляются: {self.notifier.last_error}")

    async def _notify_progress(
        self,
        *,
        title: str,
        done: int,
        total: int | None,
        new_media: int,
        media_errors: list[str] | None = None,
        new_only: bool = False,
        note: str | None = None,
        force: bool = False,
    ) -> None:
        if self.notifier is None:
            return
        now = time.monotonic()
        if not force and self.bot_every > 0 and (now - self._last_bot_time) < self.bot_every:
            return
        self._last_bot_time = now
        await self._notify(format_progress(
            chat_title=title,
            done=done,
            total=total,
            media=new_media,
            media_failed=len(media_errors or []),
            queue_left=self._queue_left,
            new_only=new_only,
            note=note,
        ))

    async def _count_messages(self, entity: Any) -> int | None:
        """Total number of messages in a chat (None when unknown)."""
        try:
            result = await self.client.get_messages(entity, limit=0)
            total = getattr(result, "total", None)
            return int(total) if total else None
        except Exception:  # noqa: BLE001 - best effort only
            return None

    async def export_entities(self, entities: list[Any]) -> int:
        self.out_root.mkdir(parents=True, exist_ok=True)
        total = len(entities)
        started = time.monotonic()
        titles = [
            getattr(entity, "title", None) or getattr(entity, "first_name", None) or str(entity)
            for entity in entities
        ]
        await self._notify(format_start(titles, queue_total=total))

        for index, entity in enumerate(entities, 1):
            title = titles[index - 1]
            self._queue_left = total - index
            self.log()
            self.log(f"[{index}/{total}] {title}")
            try:
                await self.export_chat(entity)
            except KeyboardInterrupt:
                await self._notify(
                    "⏸ <b>Экспорт прерван</b>\n"
                    f"Готово чатов: <b>{index - 1}</b> из <b>{total}</b>.\n"
                    "Чтобы продолжить, запустите экспорт с <code>--incremental</code>."
                )
                raise
            except Exception as exc:  # noqa: BLE001 - keep exporting other chats
                self.failures += 1
                message = f"{type(exc).__name__}: {exc}"
                self.log(f"[!] Не удалось экспортировать этот чат: {message}")
                await self._notify(
                    f"⚠️ <b>Чат не экспортирован</b>\n{escape(title)}\n"
                    f"<code>{escape(message[:300])}</code>"
                )

        self.progress.done()
        await self._notify(format_finish(
            chats=total,
            messages=self.fetched_total,
            media=self.media_total,
            failures=self.failures,
            seconds=time.monotonic() - started,
        ))
        return self.failures

    async def export_chat(self, entity: Any) -> None:
        now = iso_now()
        chat = build_chat_meta(entity, exported_at=now)
        peer = chat.get("id")
        chat_dir = self.out_root / f"{slugify(chat['title'], 50)} ({peer})"
        chat_dir.mkdir(parents=True, exist_ok=True)

        old_chat = read_json(chat_dir / "chat.json") or {}
        old_state = read_json(chat_dir / "state.json") or {}

        append = bool(
            self.incremental
            and not self.since
            and not self.until
            and not self.limit
            and (old_state.get("order") or old_chat.get("order") or "asc") == "asc"
            and int(old_state.get("last_message_id") or old_chat.get("last_message_id") or 0) > 0
        )

        is_forum = bool(chat.get("is_forum"))
        split = bool(is_forum and self.split_topics)

        old_topics: dict[str, Any] = old_state.get("topics") or {}
        topics_meta: dict[int, dict[str, Any]] = {}
        if split:
            if append:
                for key, value in old_topics.items():
                    try:
                        topic_id = int(key)
                    except (TypeError, ValueError):
                        continue
                    topics_meta[topic_id] = {
                        **value,
                        "id": topic_id,
                        "dir": value.get("dir") or topic_dirname(topic_id, value.get("title")),
                    }

            if is_forum:
                try:
                    for topic in await self.resolver.topics(entity):
                        meta = build_topic_meta(topic)
                        previous = topics_meta.get(topic.id) or {}
                        meta["dir"] = previous.get("dir") or topic_dirname(topic.id, meta["title"])
                        for field in ("count", "last_message_id", "last_date"):
                            if field in previous:
                                meta[field] = previous[field]
                        topics_meta[topic.id] = meta
                except Exception as exc:  # noqa: BLE001
                    self.log(f"  [i] Не удалось получить список тем: {exc}. "
                             "Темы будут определены по сообщениям.")

            if 1 not in topics_meta:
                previous = (old_topics.get("1") or {}) if append else {}
                topics_meta[1] = {
                    "id": 1,
                    "title": previous.get("title") or "General",
                    "dir": previous.get("dir") or topic_dirname(1, "General"),
                    "count": previous.get("count", 0),
                    "last_message_id": previous.get("last_message_id", 0),
                }

        last_ids: dict[int, int] = {}
        if append:
            for topic_id, meta in topics_meta.items():
                last_ids[topic_id] = int(meta.get("last_message_id") or 0)
            if not split:
                last_ids[0] = int(old_state.get("last_message_id") or 0)

        if append:
            min_id = max(last_ids.values(), default=0)
        else:
            min_id = 0

        fetch_desc = bool(self.since or self.until or self.limit)
        order = "desc" if fetch_desc else "asc"

        # Only a complete run can report "downloaded X of Y" honestly.
        self._chat_total = None
        if (
            self.notifier is not None
            and not append
            and not self.since
            and not self.until
            and self.limit is None
        ):
            self._chat_total = await self._count_messages(entity)

        pool = WriterPool(chat_dir, append=append)
        fetched = 0
        new_media = 0
        media_errors: list[str] = []
        last_date: str | None = None
        last_processed_id = min_id

        try:
            kwargs: dict[str, Any] = {
                "limit": self.limit,
                "min_id": min_id,
                "reverse": not fetch_desc,
                "wait_time": self.wait_time,
            }
            if fetch_desc and self.until is not None:
                kwargs["offset_date"] = self.until

            async for message in self.client.iter_messages(entity, **kwargs):
                message_date = getattr(message, "date", None)

                if self.since is not None and message_date and message_date < self.since:
                    break
                if self.until is not None and message_date and message_date > self.until:
                    continue

                if split:
                    topic_id = message_topic_id(message)
                    action = getattr(message, "action", None)
                    if isinstance(action, types.MessageActionTopicCreate):
                        title = getattr(action, "title", None) or f"Тема {topic_id}"
                        topics_meta.setdefault(topic_id, {
                            "id": topic_id,
                            "title": title,
                            "dir": topic_dirname(topic_id, title),
                            "count": 0,
                            "last_message_id": 0,
                        })
                    meta = topics_meta.setdefault(topic_id, {
                        "id": topic_id,
                        "title": f"Тема {topic_id}",
                        "dir": topic_dirname(topic_id, f"Тема {topic_id}"),
                        "count": 0,
                        "last_message_id": 0,
                    })
                    if append and message.id <= int(meta.get("last_message_id") or 0):
                        continue
                    rel_dir = meta["dir"]
                    topic_title = meta.get("title")
                else:
                    topic_id = None
                    rel_dir = None
                    topic_title = None
                    if append and message.id <= min_id:
                        continue

                media: dict[str, Any] | None = None
                info = plan_media(message)
                if info is not None:
                    if self.download_media:
                        media = await download_media_file(
                            self.client,
                            message,
                            info,
                            chat_dir,
                            enabled_types=self.media_types,
                            max_bytes=self.max_media_size,
                            progress=self.progress if not self.quiet else None,
                        )
                        if media.get("error"):
                            media_errors.append(f"#{message.id}: {media['error']}")
                        if media.get("downloaded"):
                            new_media += 1
                    else:
                        media = info.to_dict()
                        media["skipped"] = "скачивание отключено (--no-media)"

                data = message_to_dict(
                    message,
                    chat,
                    topic_id=message_topic_id(message) if is_forum else None,
                    media=media,
                    include_raw=self.include_raw,
                )

                pool.write(topic_id, rel_dir, topic_title, data)
                fetched += 1
                last_processed_id = max(last_processed_id, int(message.id))
                if message_date:
                    last_date = message_date.isoformat()

                if fetched % 25 == 0:
                    self.progress.status(
                        f"  сообщений: {fetched} - {format_datetime(message_date)}"
                    )
                await self._notify_progress(
                    title=chat["title"],
                    done=fetched,
                    total=self._chat_total,
                    new_media=new_media,
                    media_errors=media_errors,
                    new_only=append,
                    note=f"Последнее сообщение: {format_datetime(message_date)}",
                )
        finally:
            pool.close()
            self.progress.clear()
            self._save_state(
                chat_dir, peer, order, topics_meta, pool.stats, append,
                old_state, old_topics, last_processed_id, last_date,
            )

        stats = pool.stats
        final_topics: list[dict[str, Any]] = []
        if split:
            for topic_id in sorted(topics_meta):
                meta = dict(topics_meta[topic_id])
                stat = stats.get(topic_id) or {}
                previous = (old_topics.get(str(topic_id)) or {}) if append else {}
                meta["count"] = (int(previous.get("count") or 0) if append else 0) + int(stat.get("count") or 0)
                meta["last_message_id"] = max(
                    int(previous.get("last_message_id") or 0) if append else 0,
                    int(stat.get("max_id") or 0),
                )
                meta["last_date"] = stat.get("last_date") or previous.get("last_date")
                meta.setdefault("pinned", False)
                meta.setdefault("closed", False)
                final_topics.append(meta)
            total_messages = sum(int(topic.get("count") or 0) for topic in final_topics)
            last_message_id = max([int(t.get("last_message_id") or 0) for t in final_topics] or [0])
        else:
            stat = stats.get(None) or {}
            total_messages = (int(old_chat.get("messages") or 0) if append else 0) + int(stat.get("count") or 0)
            last_message_id = max(
                int(old_chat.get("last_message_id") or 0) if append else 0,
                int(stat.get("max_id") or 0),
            )

        media_files = (int(old_chat.get("media_files") or 0) if append else 0) + new_media

        chat.update({
            "exported_at": iso_now(),
            "first_exported_at": old_chat.get("first_exported_at") or now,
            "order": order,
            "split_topics": split,
            "formats": sorted(self.formats),
            "messages": total_messages,
            "media_files": media_files,
            "last_message_id": last_message_id,
            "dir": chat_dir.name,
            "chunks": "per-topic" if split else "single",
        })
        write_json(chat_dir / "chat.json", chat)
        write_json(chat_dir / "topics.json", {
            "generated_at": iso_now(),
            "topics": final_topics,
        })

        render_chat_dir(
            chat_dir,
            chat,
            final_topics,
            self.formats,
            order,
            log=self.log,
        )

        update_manifest(self.out_root, {
            "id": str(peer),
            "title": chat["title"],
            "type": chat.get("type"),
            "dir": chat_dir.name,
            "messages": total_messages,
            "media_files": media_files,
            "topics": sum(1 for topic in final_topics if topic.get("count")),
            "is_forum": is_forum,
            "noforwards": bool(chat.get("noforwards")),
            "formats": sorted(self.formats),
            "updated": chat["exported_at"],
        })

        self.fetched_total += fetched
        self.media_total += new_media
        self.log(
            f"  готово: новых сообщений {fetched}, всего {total_messages}, "
            f"файлов скачано {new_media}"
        )
        if chat.get("noforwards"):
            self.log("  [i] защищённый чат (пересылка запрещена) - чтение выполнено вашим аккаунтом")
        if media_errors:
            self.log(f"  [!] не удалось скачать файлов: {len(media_errors)}")
            for line in media_errors[:3]:
                self.log(f"      {line}")
        self.log(f"  -> {chat_dir}")

        reported_total = self._chat_total or fetched
        await self._notify_progress(
            title=chat["title"],
            done=fetched,
            total=max(reported_total, fetched),
            new_media=new_media,
            media_errors=media_errors,
            new_only=append,
            force=True,
        )

    def _save_state(
        self,
        chat_dir: Path,
        peer: Any,
        order: str,
        topics_meta: dict[int, dict[str, Any]],
        stats: dict[Any, dict[str, Any]],
        append: bool,
        old_state: dict[str, Any],
        old_topics: dict[str, Any],
        last_processed_id: int,
        last_date: str | None,
    ) -> None:
        state_topics: dict[str, Any] = {}
        for topic_id, meta in topics_meta.items():
            stat = stats.get(topic_id) or {}
            previous = (old_topics.get(str(topic_id)) or {}) if append else {}
            state_topics[str(topic_id)] = {
                "title": meta.get("title"),
                "dir": meta.get("dir"),
                "last_message_id": max(
                    int(previous.get("last_message_id") or 0) if append else 0,
                    int(stat.get("max_id") or 0),
                ),
                "last_date": stat.get("last_date") or previous.get("last_date"),
                "count": (int(previous.get("count") or 0) if append else 0) + int(stat.get("count") or 0),
                "pinned": bool(meta.get("pinned")),
                "closed": bool(meta.get("closed")),
            }

        if topics_meta:
            last_message_id = max(
                [int(item.get("last_message_id") or 0) for item in state_topics.values()]
                + [int(last_processed_id or 0)]
            )
        else:
            stat = stats.get(None) or {}
            last_message_id = max(
                int(old_state.get("last_message_id") or 0) if append else 0,
                int(stat.get("max_id") or 0),
                int(last_processed_id or 0),
            )

        write_json(chat_dir / "state.json", {
            "chat_id": peer,
            "updated_at": iso_now(),
            "order": order,
            "last_message_id": last_message_id,
            "last_date": last_date or old_state.get("last_date"),
            "topics": state_topics,
        })
