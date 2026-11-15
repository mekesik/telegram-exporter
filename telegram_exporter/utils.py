"""Small helpers: names, dates, sizes, JSON files."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

_INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_FS = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}
_WS = re.compile(r"\s+")
_SIZE_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([kmgt]?i?b?)?\s*$", re.IGNORECASE)
_SIZE_UNITS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024 ** 2,
    "mb": 1024 ** 2,
    "mib": 1024 ** 2,
    "g": 1024 ** 3,
    "gb": 1024 ** 3,
    "gib": 1024 ** 3,
    "t": 1024 ** 4,
    "tb": 1024 ** 4,
    "tib": 1024 ** 4,
}


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Return a filename that is safe on Windows, macOS and Linux."""
    name = _INVALID_FS.sub("_", str(name or "")).strip().rstrip(". ")
    if not name:
        name = "file"

    path = Path(name)
    suffix = _INVALID_FS.sub("", path.suffix)
    if len(suffix) > 12 or " " in suffix:
        suffix = ""
    stem = _INVALID_FS.sub("_", path.stem).strip().rstrip(". ") or "file"
    if stem.upper() in _RESERVED_FS:
        stem = "_" + stem

    budget = max(16, max_len - len(suffix))
    stem = stem[:budget].rstrip(". ")
    return (stem or "file") + suffix


def slugify(text: str, max_len: int = 60) -> str:
    """Filesystem-friendly slug that keeps Cyrillic and other unicode letters."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = re.sub(r"[^\w\s.-]+", "", text, flags=re.UNICODE)
    text = _WS.sub("_", text).strip("._-")
    text = text[:max_len].strip("._-")
    return text or "chat"


def human_size(size: int | float | None) -> str:
    if not size or size < 0:
        return "?"
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            if unit == "Б":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ТБ"


def parse_size(value: str | int | None) -> int:
    """Parse ``500MB`` / ``1.5 GB`` / ``12345`` into bytes."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    match = _SIZE_RE.match(str(value))
    if not match:
        raise ValueError(f"Не понимаю размер: {value!r}. Примеры: 200MB, 1.5GB, 0")
    number = float(match.group(1).replace(",", "."))
    unit = (match.group(2) or "").lower()
    return max(0, int(number * _SIZE_UNITS.get(unit, 1)))


def parse_datetime(
    value: str | int | float | datetime | None,
    *,
    end_of_day: bool = False,
) -> datetime | None:
    """Parse a date/datetime. Naive values are treated as local time.

    ``end_of_day=True`` makes a date-only value mean 23:59:59.999999 of that
    day (used for an inclusive ``--until``).
    """
    if value is None or value == "":
        return None
    date_only = False
    if isinstance(value, datetime):
        result = value
        date_only = value.hour == 0 and value.minute == 0 and value.second == 0
    elif isinstance(value, (int, float)):
        result = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        result = None
        date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}", text))
        if re.fullmatch(r"\d{9,13}", text):
            stamp = int(text)
            if len(text) >= 13:
                stamp /= 1000
            result = datetime.fromtimestamp(stamp, tz=timezone.utc)
        if result is None:
            try:
                result = datetime.fromisoformat(text)
            except ValueError:
                for fmt in (
                    "%Y-%m-%d",
                    "%d.%m.%Y",
                    "%Y-%m-%d %H:%M",
                    "%d.%m.%Y %H:%M",
                    "%Y-%m-%d %H:%M:%S",
                ):
                    try:
                        result = datetime.strptime(text, fmt)
                        break
                    except ValueError:
                        continue
        if result is None:
            raise ValueError(
                f"Не понимаю дату: {value!r}. Примеры: 2024-01-31, 31.01.2024, "
                "2024-01-31T12:30"
            )

    if result.tzinfo is None:
        result = result.astimezone()
    if end_of_day and date_only:
        result = result.replace(hour=23, minute=59, second=59, microsecond=999999)
    return result


def format_datetime(value: str | datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is not None:
        value = value.astimezone()
    return value.strftime(fmt)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def quote_path(path: str) -> str:
    """URL-encode a relative filesystem path, keeping slashes."""
    return quote(path.replace("\\", "/"), safe="/")


def ensure_dir(path: str | Path) -> Path:
    result = Path(path)
    result.mkdir(parents=True, exist_ok=True)
    return result


def read_json(path: str | Path) -> dict[str, Any] | None:
    file = Path(path)
    if not file.exists():
        return None
    try:
        with file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_json(path: str | Path, data: Any) -> None:
    file = Path(path)
    ensure_dir(file.parent)
    tmp = file.with_name(file.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, file)


def unique_suffix(path: Path) -> Path:
    """Return ``path`` or ``path_2``, ``path_3``... if it already exists."""
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path


def chunked(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    chunk: list[Any] = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk
