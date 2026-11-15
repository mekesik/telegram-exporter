"""Media classification and downloading."""

from __future__ import annotations

import mimetypes
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from telethon import errors
from telethon.tl import types

from .utils import human_size, sanitize_filename

SUBDIRS = {
    "photo": "photos",
    "video": "videos",
    "round": "round",
    "voice": "voice",
    "audio": "audio",
    "sticker": "stickers",
    "gif": "gifs",
    "file": "files",
}

DOWNLOADABLE = set(SUBDIRS)

_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "application/x-tgsticker": ".tgs",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/x-rar-compressed": ".rar",
    "application/x-7z-compressed": ".7z",
    "application/vnd.rar": ".rar",
    "text/plain": ".txt",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(getattr(value, "text", value))


def _extension(mime: str | None, fallback: str = "") -> str:
    if mime in _MIME_EXT:
        return _MIME_EXT[mime]
    if mime:
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return guessed
    return fallback


@dataclass
class MediaInfo:
    kind: str
    filename: str
    size: int | None = None
    mime: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    title: str | None = None
    performer: str | None = None
    downloadable: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "filename": self.filename,
            "size": self.size,
            "mime": self.mime,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "title": self.title,
            "performer": self.performer,
            "extra": self.extra or None,
            "file": None,
            "downloaded": False,
            "cached": False,
            "skipped": None,
            "error": None,
        }


def _photo_info(media: types.MessageMediaPhoto) -> MediaInfo:
    photo = getattr(media, "photo", None)
    width = height = None
    sizes = getattr(photo, "sizes", None) or []
    best = 0
    for size in sizes:
        w = getattr(size, "w", 0) or 0
        h = getattr(size, "h", 0) or 0
        if w * h >= best:
            best = w * h
            width, height = w or None, h or None
    return MediaInfo(
        kind="photo",
        filename="photo.jpg",
        mime="image/jpeg",
        width=width,
        height=height,
        downloadable=True,
    )


def _document_info(media: types.MessageMediaDocument) -> MediaInfo | None:
    document = getattr(media, "document", None)
    if not isinstance(document, types.Document):
        return MediaInfo(kind="other", filename="document.bin", downloadable=False,
                         extra={"note": "документ недоступен"})

    attrs = {type(attr): attr for attr in (document.attributes or [])}
    mime = getattr(document, "mime_type", None)
    size = getattr(document, "size", None)
    filename_attr = attrs.get(types.DocumentAttributeFilename)
    original = getattr(filename_attr, "file_name", None) if filename_attr else None

    sticker = attrs.get(types.DocumentAttributeSticker)
    animated = attrs.get(types.DocumentAttributeAnimated)
    audio = attrs.get(types.DocumentAttributeAudio)
    video = attrs.get(types.DocumentAttributeVideo)

    width = height = duration = None
    title = performer = None

    if sticker is not None:
        kind = "sticker"
        ext = _extension(mime, ".webp")
        filename = sanitize_filename(original) if original else f"sticker{ext}"
        if not Path(filename).suffix:
            filename += ext
        return MediaInfo(
            kind=kind, filename=filename, size=size, mime=mime,
            width=getattr(attrs.get(types.DocumentAttributeImageSize), "w", None),
            height=getattr(attrs.get(types.DocumentAttributeImageSize), "h", None),
            downloadable=True,
        )

    if animated is not None:
        kind = "gif"
        ext = _extension(mime, ".mp4")
        filename = sanitize_filename(original) if original else f"animation{ext}"
        if not Path(filename).suffix:
            filename += ext
        if video is not None:
            width, height, duration = video.w, video.h, video.duration
        return MediaInfo(kind=kind, filename=filename, size=size, mime=mime,
                         width=width, height=height, duration=duration, downloadable=True)

    if audio is not None:
        kind = "voice" if getattr(audio, "voice", False) or getattr(media, "voice", False) else "audio"
        ext = _extension(mime, ".ogg" if kind == "voice" else ".mp3")
        title = getattr(audio, "title", None)
        performer = getattr(audio, "performer", None)
        duration = getattr(audio, "duration", None)
        if original:
            filename = sanitize_filename(original)
        elif title:
            base = f"{performer} - {title}" if performer else str(title)
            filename = sanitize_filename(base) or f"{kind}{ext}"
        else:
            filename = f"{kind}{ext}"
        if not Path(filename).suffix:
            filename += ext
        return MediaInfo(kind=kind, filename=filename, size=size, mime=mime,
                         duration=duration, title=title, performer=performer,
                         downloadable=True)

    if video is not None:
        round_video = bool(getattr(video, "round_message", False) or getattr(media, "round", False))
        kind = "round" if round_video else "video"
        ext = _extension(mime, ".mp4")
        filename = sanitize_filename(original) if original else f"{kind}{ext}"
        if not Path(filename).suffix:
            filename += ext
        return MediaInfo(kind=kind, filename=filename, size=size, mime=mime,
                         width=video.w, height=video.h, duration=video.duration,
                         downloadable=True)

    kind = "file"
    ext = _extension(mime, "")
    filename = sanitize_filename(original) if original else f"file{ext or '.bin'}"
    if not Path(filename).suffix and ext:
        filename += ext
    return MediaInfo(kind=kind, filename=filename, size=size, mime=mime,
                     downloadable=True)


def plan_media(message: Any) -> MediaInfo | None:
    """Return a description of the message media without downloading it."""
    media = getattr(message, "media", None)
    if media is None:
        return None

    if isinstance(media, types.MessageMediaPhoto):
        return _photo_info(media)

    if isinstance(media, types.MessageMediaDocument):
        return _document_info(media)

    if isinstance(media, types.MessageMediaWebPage):
        page = getattr(media, "webpage", None)
        if page is None or type(page).__name__ == "WebPageEmpty":
            return None
        return MediaInfo(
            kind="webpage",
            filename="link",
            downloadable=False,
            extra={
                "url": getattr(page, "url", None),
                "title": getattr(page, "title", None),
                "description": getattr(page, "description", None),
                "site_name": getattr(page, "site_name", None),
                "type": getattr(page, "type", None),
            },
        )

    if isinstance(media, types.MessageMediaPoll):
        poll = media.poll
        results = media.results
        answers = []
        votes_by_option = {
            getattr(v, "option", b""): getattr(v, "voters", 0)
            for v in (getattr(results, "results", None) or [])
        }
        chosen = {
            getattr(v, "option", b"")
            for v in (getattr(results, "results", None) or [])
            if getattr(v, "chosen", False)
        }
        for answer in getattr(poll, "answers", None) or []:
            option = getattr(answer, "option", b"")
            answers.append({
                "text": _text(getattr(answer, "text", "")),
                "votes": int(votes_by_option.get(option, 0)),
                "chosen": option in chosen,
            })
        return MediaInfo(
            kind="poll",
            filename="poll",
            downloadable=False,
            extra={
                "question": _text(getattr(poll, "question", "")),
                "answers": answers,
                "total_voters": getattr(results, "total_voters", None),
                "quiz": bool(getattr(poll, "quiz", False)),
                "closed": bool(getattr(poll, "closed", False)),
                "multiple_choice": bool(getattr(poll, "multiple_choice", False)),
                "solution": _text(getattr(results, "solution", "")) or None,
            },
        )

    if isinstance(media, types.MessageMediaGeo):
        geo = media.geo
        return MediaInfo(kind="geo", filename="geo", downloadable=False,
                         extra={"lat": getattr(geo, "lat", None), "long": getattr(geo, "long", None)})

    if isinstance(media, types.MessageMediaGeoLive):
        geo = media.geo
        return MediaInfo(kind="geo", filename="geo", downloadable=False,
                         extra={"lat": getattr(geo, "lat", None), "long": getattr(geo, "long", None),
                                "live": True, "period": getattr(media, "period", None)})

    if isinstance(media, types.MessageMediaVenue):
        geo = media.geo
        return MediaInfo(kind="geo", filename="venue", downloadable=False,
                         extra={"lat": getattr(geo, "lat", None), "long": getattr(geo, "long", None),
                                "title": getattr(media, "title", None),
                                "address": getattr(media, "address", None)})

    if isinstance(media, types.MessageMediaContact):
        return MediaInfo(kind="contact", filename="contact", downloadable=False,
                         extra={"first_name": media.first_name, "last_name": media.last_name,
                                "phone": media.phone_number, "user_id": media.user_id})

    if isinstance(media, types.MessageMediaDice):
        return MediaInfo(kind="dice", filename="dice", downloadable=False,
                         extra={"emoticon": media.emoticon, "value": media.value})

    if isinstance(media, types.MessageMediaGame):
        game = media.game
        return MediaInfo(kind="game", filename="game", downloadable=False,
                         extra={"title": getattr(game, "title", None),
                                "description": getattr(game, "description", None)})

    if isinstance(media, types.MessageMediaInvoice):
        return MediaInfo(kind="invoice", filename="invoice", downloadable=False,
                         extra={"title": media.title, "description": media.description,
                                "currency": media.currency, "total_amount": media.total_amount})

    if isinstance(media, types.MessageMediaStory):
        return MediaInfo(kind="story", filename="story", downloadable=False, extra={})

    if isinstance(media, types.MessageMediaGiveaway):
        return MediaInfo(kind="giveaway", filename="giveaway", downloadable=False, extra={})

    if isinstance(media, types.MessageMediaGiveawayResults):
        return MediaInfo(kind="giveaway", filename="giveaway", downloadable=False, extra={})

    return MediaInfo(kind="other", filename="attachment", downloadable=False,
                     extra={"class": type(media).__name__})


async def download_media_file(
    client: Any,
    message: Any,
    info: MediaInfo,
    chat_dir: Path,
    *,
    enabled_types: set[str],
    max_bytes: int = 0,
    progress: Any = None,
) -> dict[str, Any]:
    """Download one message's media and return the JSON media descriptor."""
    data = info.to_dict()

    if info.kind not in enabled_types:
        data["skipped"] = "тип медиа отключён"
        return data
    if not info.downloadable:
        return data
    if max_bytes and info.size and info.size > max_bytes:
        data["skipped"] = f"размер {human_size(info.size)} больше лимита {human_size(max_bytes)}"
        return data

    subdir = SUBDIRS.get(info.kind, "files")
    name = sanitize_filename(f"{message.id}_{info.filename}", max_len=100)
    dest_dir = chat_dir / "media" / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name

    rel_path = f"media/{subdir}/{name}"
    if dest.exists() and dest.stat().st_size > 0:
        data.update({"file": rel_path, "downloaded": True, "cached": True,
                     "size": dest.stat().st_size})
        return data

    last_update = [0.0]

    def on_progress(received: int, total: int) -> None:
        if progress is None or not total or total < 1024 * 1024:
            return
        now = time.monotonic()
        if now - last_update[0] < 0.4:
            return
        last_update[0] = now
        percent = int(received * 100 / total)
        progress.status(f"    загрузка {name}: {percent}% ({human_size(received)} / {human_size(total)})")

    try:
        result = await client.download_media(message, file=str(dest), progress_callback=on_progress)
    except errors.FloodWaitError as exc:
        # Client already sleeps for waits below flood_sleep_threshold; if we are
        # here, the server asked to wait longer than that threshold.
        data["error"] = f"FloodWait {exc.seconds} с — повторите экспорт позже"
        return data
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the export
        data["error"] = f"{type(exc).__name__}: {exc}"
        if dest.exists() and dest.stat().st_size == 0:
            try:
                dest.unlink()
            except OSError:
                pass
        return data
    finally:
        if progress is not None:
            progress.clear()

    if result is None or not dest.exists() or dest.stat().st_size == 0:
        data["error"] = "файл не получен (возможно, истёк срок хранения или доступ ограничен)"
        if dest.exists() and dest.stat().st_size == 0:
            try:
                dest.unlink()
            except OSError:
                pass
        return data

    data.update({"file": rel_path, "downloaded": True, "size": dest.stat().st_size})
    return data
