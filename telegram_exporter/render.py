"""Render chat JSONL into readable HTML/TXT/CSV/JSON."""

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path
from typing import Any, Iterator

from .utils import (
    format_datetime,
    human_size,
    iso_now,
    quote_path,
    read_json,
    write_json,
)

TYPE_LABELS = {
    "user": "личный чат",
    "bot": "бот",
    "group": "группа",
    "supergroup": "супергруппа",
    "channel": "канал",
    "saved": "избранное",
    "unknown": "чат",
}

CSS = r"""
:root{
  --bg:#eef1f5;--card:#ffffff;--text:#1c232b;--muted:#6b7683;--line:#dde3ea;
  --accent:#2b7cd3;--accent-soft:#e8f1fb;--media:#f2f5f8;--shadow:0 1px 2px rgba(16,24,40,.06);
}
@media (prefers-color-scheme:dark){
  :root{--bg:#11161c;--card:#182028;--text:#e6ebf1;--muted:#93a0ad;--line:#26313c;
        --accent:#63a9f0;--accent-soft:#1b2b3c;--media:#131a21;--shadow:0 1px 2px rgba(0,0,0,.4);}
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);
     font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:22px 16px 60px}.appbar{display:flex;justify-content:space-between;align-items:center;margin:0 0 16px}.brand{font-weight:750;letter-spacing:.02em}.lang-toggle{border:1px solid var(--line);background:var(--card);color:var(--text);border-radius:9px;padding:7px 12px;cursor:pointer}.topic-list{display:grid;gap:8px}.topic-row{display:flex;align-items:center;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;box-shadow:var(--shadow)}.topic-icon{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;background:var(--accent-soft);font-weight:700;color:var(--accent);flex:none}.topic-info{min-width:0;flex:1}.topic-info strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.topic-info small{color:var(--muted)}.topic-count{color:var(--muted);font-size:12px;white-space:nowrap}.msg{max-width:820px}.appbar{position:sticky;top:0;z-index:4;padding:10px 0;background:var(--bg)}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.chat-head{background:var(--card);border:1px solid var(--line);border-radius:14px;
           padding:18px 22px;margin-bottom:16px;box-shadow:var(--shadow)}
.chat-head h1{margin:2px 0 4px;font-size:22px;line-height:1.25;overflow-wrap:anywhere}
.chat-head .sub{color:var(--muted);font-size:13px}
.chat-head .crumbs{font-size:13px;margin-bottom:6px}
.notice{margin-top:12px;padding:9px 12px;border-radius:9px;background:var(--accent-soft);
        color:var(--text);font-size:13px}
.msg{background:var(--card);border:1px solid var(--line);border-radius:12px;
     padding:12px 15px;margin:10px 0;box-shadow:var(--shadow);overflow-wrap:anywhere}
.msg.service{background:transparent;border-style:dashed;box-shadow:none}
.msg .top{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;margin-bottom:4px}
.msg .sender{font-weight:650;color:var(--text)}
.msg .time{font-size:12px;color:var(--muted)}
.msg .badges{font-size:12px;color:var(--muted);display:flex;gap:7px;flex-wrap:wrap}
.msg .text{white-space:pre-wrap}
.msg .text a{overflow-wrap:anywhere}
.msg blockquote{margin:6px 0 6px;padding:2px 0 2px 12px;border-left:3px solid var(--accent);color:var(--muted)}
.msg code,.msg pre{background:var(--media);border-radius:6px;padding:1px 5px;
                  font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13px}
.msg pre{padding:9px 11px;overflow:auto}
.spoiler{background:var(--muted);color:transparent;border-radius:4px;padding:0 3px}
.spoiler:hover{color:var(--text);background:var(--media)}
.fwd,.reply{font-size:13px;color:var(--muted);margin:4px 0}
.fwd b,.reply b{color:var(--accent);font-weight:600}
.bottom{margin-top:8px;font-size:12px;color:var(--muted);display:flex;gap:12px;flex-wrap:wrap}
.reactions{display:inline-flex;gap:6px;flex-wrap:wrap}
.reaction{background:var(--accent-soft);border-radius:999px;padding:1px 8px;font-size:12px;color:var(--text)}
.media{margin:9px 0 2px}
.media img,.media video{max-width:100%;max-height:560px;border-radius:10px;display:block;background:var(--media)}
.media video.round{border-radius:50%;width:280px;height:280px;object-fit:cover}
.media audio{width:100%;max-width:440px}
.media-missing{background:var(--media);border:1px dashed var(--line);color:var(--muted);
               border-radius:8px;padding:9px 11px;font-size:13px;display:inline-block}
.file-link{display:inline-flex;gap:9px;align-items:center;background:var(--media);
           border:1px solid var(--line);border-radius:9px;padding:9px 12px;max-width:100%}
.file-link .size{color:var(--muted);font-size:12px;white-space:nowrap}
.poll{background:var(--media);border:1px solid var(--line);border-radius:10px;padding:12px 14px;max-width:560px}
.poll .q{font-weight:600;margin-bottom:8px}
.poll .opt{position:relative;margin:5px 0;padding:6px 10px;border-radius:7px;overflow:hidden;background:var(--card)}
.poll .bar{position:absolute;inset:0;background:var(--accent-soft);z-index:0}
.poll .opt span{position:relative;z-index:1}
.poll .votes{float:right;color:var(--muted);font-size:12px}
.webpage{display:block;background:var(--media);border-left:3px solid var(--accent);
         border-radius:7px;padding:8px 11px;margin:8px 0;max-width:560px}
.webpage .site{font-size:12px;color:var(--muted)}
.geo{background:var(--media);border-radius:8px;padding:8px 11px;display:inline-block}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
      border-radius:12px;overflow:hidden;box-shadow:var(--shadow)}
th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);background:var(--media)}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;white-space:nowrap}
.topic-title{font-weight:600}
.badge{display:inline-block;background:var(--media);border:1px solid var(--line);border-radius:999px;
       padding:0 7px;font-size:11px;color:var(--muted);margin-left:5px;vertical-align:1px}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:26px}
.empty{color:var(--muted);padding:20px;text-align:center}
"""


def _type_label(chat_type: str | None) -> str:
    return TYPE_LABELS.get(chat_type or "", "чат")


def _format_duration(seconds: float | int | None) -> str:
    if not seconds:
        return ""
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def _file_url(prefix: str, path: str | None) -> str | None:
    if not path:
        return None
    return prefix + quote_path(path)


def _media_block(media: dict[str, Any] | None, prefix: str) -> str:
    if not media:
        return ""
    kind = media.get("kind")
    url = _file_url(prefix, media.get("file"))
    name = escape(str(media.get("filename") or "файл"))
    size = human_size(media.get("size")) if media.get("size") else ""
    error = media.get("error") or media.get("skipped")

    if kind == "photo":
        if not url:
            return f'<div class="media"><div class="media-missing">Фото не скачано{": " + escape(str(error)) if error else ""}</div></div>'
        w = media.get("width")
        h = media.get("height")
        attrs = f' width="{w}" height="{h}"' if w and h else ""
        return (f'<div class="media"><a href="{url}" target="_blank" rel="noopener">'
                f'<img src="{url}" loading="lazy" alt="{name}"{attrs}></a></div>')

    if kind in {"video", "round"}:
        if not url:
            return f'<div class="media"><div class="media-missing">Видео не скачано{": " + escape(str(error)) if error else ""}</div></div>'
        cls = "round" if kind == "round" else ""
        label = f' · {_format_duration(media.get("duration"))}' if media.get("duration") else ""
        return (f'<div class="media"><video class="{cls}" controls preload="metadata" playsinline src="{url}">'
                f'</video><div class="bottom">{name}{label}</div></div>')

    if kind in {"voice", "audio"}:
        if not url:
            return f'<div class="media"><div class="media-missing">Аудио не скачано{": " + escape(str(error)) if error else ""}</div></div>'
        title = media.get("title") or ("Голосовое сообщение" if kind == "voice" else "Аудио")
        performer = media.get("performer")
        label = f"{escape(str(performer))} — " if performer else ""
        label += escape(str(title))
        duration = _format_duration(media.get("duration"))
        return (f'<div class="media"><audio controls preload="none" src="{url}"></audio>'
                f'<div class="bottom">{label}{" · " + duration if duration else ""}</div></div>')

    if kind == "sticker":
        if not url:
            return '<div class="media"><div class="media-missing">Стикер не скачан</div></div>'
        if url.endswith(".webm"):
            return f'<div class="media"><video autoplay loop muted playsinline src="{url}"></video></div>'
        if url.endswith(".tgs"):
            return f'<div class="media"><a class="file-link" href="{url}">🧩 Стикер (.tgs) <span class="size">{size}</span></a></div>'
        return f'<div class="media"><img src="{url}" loading="lazy" alt="sticker" style="max-width:220px"></div>'

    if kind == "gif":
        if not url:
            return '<div class="media"><div class="media-missing">GIF не скачан</div></div>'
        return f'<div class="media"><video autoplay loop muted playsinline src="{url}"></video></div>'

    if kind == "file":
        if not url:
            return f'<div class="media"><div class="media-missing">Файл не скачан: {name}{" · " + escape(str(error)) if error else ""}</div></div>'
        return (f'<div class="media"><a class="file-link" href="{url}" download>📎 <span>{name}</span>'
                f'<span class="size">{size}</span></a></div>')

    if kind == "poll":
        extra = media.get("extra") or {}
        answers = extra.get("answers") or []
        max_votes = max([a.get("votes", 0) for a in answers] or [1]) or 1
        options = []
        for answer in answers:
            votes = int(answer.get("votes") or 0)
            width = int(votes * 100 / max_votes) if max_votes else 0
            chosen = " ✓" if answer.get("chosen") else ""
            options.append(
                f'<div class="opt"><div class="bar" style="width:{width}%"></div>'
                f'<span>{escape(str(answer.get("text") or ""))}{chosen}</span>'
                f'<span class="votes">{votes}</span></div>'
            )
        total = extra.get("total_voters")
        quiz = " · викторина" if extra.get("quiz") else ""
        return (f'<div class="media"><div class="poll"><div class="q">'
                f'📊 {escape(str(extra.get("question") or "Опрос"))}</div>{"".join(options)}'
                f'<div class="bottom">Всего голосов: {total if total is not None else "?"}{quiz}</div></div></div>')

    if kind == "geo":
        extra = media.get("extra") or {}
        lat, lon = extra.get("lat"), extra.get("long")
        if lat is None or lon is None:
            return ""
        title = extra.get("title")
        address = extra.get("address")
        label = " · ".join(escape(str(x)) for x in (title, address) if x) or "Геолокация"
        return (f'<div class="media"><a class="geo" target="_blank" rel="noopener" '
                f'href="https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}">'
                f'🗺 {label} ({lat:.5f}, {lon:.5f})</a></div>')

    if kind == "contact":
        extra = media.get("extra") or {}
        name = " ".join(str(x) for x in (extra.get("first_name"), extra.get("last_name")) if x) or "Контакт"
        phone = str(extra.get("phone") or "")
        return (f'<div class="media"><div class="geo">👤 {escape(name)}'
                f'{" · " + escape(phone) if phone else ""}</div></div>')

    if kind == "dice":
        extra = media.get("extra") or {}
        return (f'<div class="media"><div style="font-size:42px;line-height:1">'
                f'{escape(str(extra.get("emoticon") or "🎲"))} <span style="font-size:20px">{extra.get("value", "")}</span></div></div>')

    if kind == "webpage":
        extra = media.get("extra") or {}
        link = extra.get("url")
        title = extra.get("title") or extra.get("site_name") or link
        if not link or not title:
            return ""
        site = extra.get("site_name") or ""
        return (f'<a class="webpage" href="{escape(str(link), quote=True)}" target="_blank" rel="noopener">'
                f'<div class="site">{escape(str(site))}</div><div>{escape(str(title))}</div></a>')

    if kind == "game":
        extra = media.get("extra") or {}
        return (f'<div class="media"><div class="geo">🎮 {escape(str(extra.get("title") or "Игра"))}'
                f'{" · " + escape(str(extra.get("description"))) if extra.get("description") else ""}</div></div>')

    if kind == "invoice":
        extra = media.get("extra") or {}
        amount = extra.get("total_amount")
        currency = extra.get("currency") or ""
        return (f'<div class="media"><div class="geo">🧾 {escape(str(extra.get("title") or "Счёт"))}'
                f'{" · " + str(amount) + " " + escape(str(currency)) if amount is not None else ""}</div></div>')

    if kind == "story":
        return '<div class="media"><div class="media-missing">История (недоступна для скачивания)</div></div>'

    if kind == "giveaway":
        return '<div class="media"><div class="media-missing">Розыгрыш</div></div>'

    if kind == "other":
        extra = media.get("extra") or {}
        note = extra.get("note") or extra.get("class") or "вложение"
        return f'<div class="media"><div class="media-missing">{escape(str(note))}</div></div>'

    return ""


def _message_html(message: dict[str, Any], media_prefix: str) -> str:
    message_id = message.get("id")
    service = message.get("type") == "service"
    classes = "msg service" if service else "msg"
    parts = [f'<article class="{classes}" id="m{message_id}">']

    top: list[str] = []
    if not service:
        sender = message.get("sender_name")
        if sender:
            top.append(f'<span class="sender">{escape(str(sender))}</span>')
    date = format_datetime(message.get("date"))
    if date:
        top.append(f'<a class="time" href="#m{message_id}">{escape(date)}</a>')

    badges: list[str] = []
    if message.get("pinned"):
        badges.append("📌 закреплено")
    if message.get("edited"):
        badges.append("изменено")
    if message.get("noforwards"):
        badges.append("🔒 без пересылки")
    if badges:
        top.append(f'<span class="badges">{" · ".join(badges)}</span>')
    if top:
        parts.append(f'<div class="top">{"".join(top)}</div>')

    forwarded = message.get("forwarded_from")
    if forwarded:
        source = (forwarded.get("from_name") or forwarded.get("post_author")
                  or forwarded.get("from_id") or forwarded.get("saved_from_peer") or "неизвестно")
        parts.append(f'<div class="fwd">Переслано от <b>{escape(str(source))}</b></div>')

    reply = message.get("reply_to")
    if reply and reply.get("message_id"):
        parts.append(
            f'<div class="reply">↩ ответ на <a href="#m{reply["message_id"]}">'
            f'сообщение #{reply["message_id"]}</a></div>'
        )

    action = message.get("action")
    text_html = message.get("text_html") or ""
    if action:
        description = action.get("text") or action.get("type") or "служебное сообщение"
        parts.append(f'<div class="text">⚙️ <i>{escape(str(description))}</i></div>')
    if text_html:
        parts.append(f'<div class="text">{text_html}</div>')

    parts.append(_media_block(message.get("media"), media_prefix))

    bottom: list[str] = []
    if message.get("views") is not None:
        bottom.append(f'👁 {message["views"]}')
    if message.get("forwards") is not None:
        bottom.append(f'↗ {message["forwards"]}')
    reactions = message.get("reactions") or []
    if reactions:
        chips = "".join(
            f'<span class="reaction">{escape(str(r.get("emoji") or "?"))} {r.get("count", 0)}</span>'
            for r in reactions
        )
        bottom.append(f'<span class="reactions">{chips}</span>')
    if bottom:
        parts.append(f'<div class="bottom">{" ".join(bottom)}</div>')

    parts.append("</article>")
    return "".join(parts)


def _html_head(
    title: str,
    subtitle: str,
    *,
    back_href: str | None = None,
    back_label: str = "← Назад",
    notice: str | None = None,
) -> str:
    back = f'<div class="crumbs"><a href="{escape(back_href, quote=True)}">{escape(back_label)}</a></div>' if back_href else ""
    notice_html = f'<div class="notice">{escape(notice)}</div>' if notice else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{CSS}</style>
</head>
<body><div class="wrap">
<div class="appbar"><div class="brand">Tgk <span>Alg0rithmX</span></div><button class="lang-toggle" id="lang-toggle" type="button" aria-label="Switch language">EN</button></div>
<header class="chat-head">{back}<h1>{escape(title)}</h1><div class="sub">{escape(subtitle)}</div>{notice_html}</header>
<main>
"""


HTML_FOOTER = """</main>
<footer data-ru="Создано Tgk Alg0rithmX · просмотр работает локально" data-en="Made with Tgk Alg0rithmX · local archive viewer">Создано Tgk Alg0rithmX · просмотр работает локально</footer>
</div><script>
(()=>{const key='tgk-language';const btn=document.getElementById('lang-toggle');if(!btn)return;let lang=localStorage.getItem(key)||'ru';function apply(){document.documentElement.lang=lang;btn.textContent=lang==='ru'?'EN':'RU';document.querySelectorAll('[data-ru][data-en]').forEach(el=>el.textContent=el.dataset[lang]);document.querySelectorAll('[data-i18n]').forEach(el=>el.textContent=el.dataset.i18n==='topics'?(lang==='ru'?'Темы':'Topics'):el.textContent)}btn.addEventListener('click',()=>{lang=lang==='ru'?'en':'ru';localStorage.setItem(key,lang);apply()});apply()})();
</script></body></html>
"""


def _human_subtitle(chat_meta: dict[str, Any], extra: str = "") -> str:
    bits: list[str] = []
    username = chat_meta.get("username")
    if username:
        bits.append(f"@{username}")
    bits.append(_type_label(chat_meta.get("type")))
    count = chat_meta.get("messages")
    if count is not None:
        bits.append(f"{count} сообщений")
    if extra:
        bits.append(extra)
    exported = format_datetime(chat_meta.get("exported_at"), "%d.%m.%Y %H:%M")
    if exported:
        bits.append(f"экспорт {exported}")
    return " · ".join(bits)


def iter_jsonl(path: Path, reverse: bool = False) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    if not reverse:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
        return

    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        buffer = b""
        while position > 0:
            size = min(65536, position)
            position -= size
            handle.seek(position)
            data = handle.read(size) + buffer
            lines = data.split(b"\n")
            buffer = lines.pop(0) if position > 0 else b""
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
        if buffer.strip():
            try:
                yield json.loads(buffer.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                pass


def render_source(
    source: Path,
    out_dir: Path,
    *,
    title: str,
    subtitle: str,
    formats: set[str],
    order: str,
    media_prefix: str,
    back_href: str | None = None,
    back_label: str = "← Назад",
    notice: str | None = None,
    log=None,
) -> int:
    """Render one messages.jsonl into the requested formats. Returns message count."""
    if not source.exists() or source.stat().st_size == 0:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    reverse = order == "desc"
    count = 0

    if "html" in formats:
        with (out_dir / "messages.html").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(_html_head(title, subtitle, back_href=back_href, back_label=back_label, notice=notice))
            for message in iter_jsonl(source, reverse=reverse):
                handle.write(_message_html(message, media_prefix))
                count += 1
            if count == 0:
                handle.write('<div class="empty">Сообщений нет</div>')
            handle.write(HTML_FOOTER)
    else:
        for _ in iter_jsonl(source):
            count += 1

    if "txt" in formats:
        with (out_dir / "messages.txt").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(f"# {title}\n# {subtitle}\n\n")
            for message in iter_jsonl(source, reverse=reverse):
                handle.write(_message_text(message))

    if "csv" in formats:
        with (out_dir / "messages.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "id", "date", "type", "sender_id", "sender_name", "text",
                "media_kind", "media_file", "media_size", "reply_to",
                "forwarded_from", "views", "forwards", "grouped_id",
                "topic_id", "edited", "service",
            ])
            for message in iter_jsonl(source, reverse=reverse):
                media = message.get("media") or {}
                reply = message.get("reply_to") or {}
                forwarded = message.get("forwarded_from") or {}
                action = message.get("action") or {}
                writer.writerow([
                    message.get("id"),
                    message.get("date"),
                    message.get("type"),
                    message.get("sender_id"),
                    message.get("sender_name"),
                    message.get("text") or action.get("text") or "",
                    media.get("kind") or "",
                    media.get("file") or "",
                    media.get("size") or "",
                    reply.get("message_id") or "",
                    forwarded.get("from_name") or forwarded.get("from_id") or "",
                    message.get("views") if message.get("views") is not None else "",
                    message.get("forwards") if message.get("forwards") is not None else "",
                    message.get("grouped_id") or "",
                    message.get("topic_id") or "",
                    message.get("edited") or "",
                    "1" if message.get("type") == "service" else "",
                ])

    if "json" in formats:
        with (out_dir / "messages.json").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("[\n")
            first = True
            for message in iter_jsonl(source, reverse=reverse):
                if not first:
                    handle.write(",\n")
                handle.write(json.dumps(message, ensure_ascii=False, indent=2))
                first = False
            handle.write("\n]\n")

    if log:
        log(f"  отрисовано: {count} сообщений -> {out_dir.name}/messages.*")
    return count


def _message_text(message: dict[str, Any]) -> str:
    date = format_datetime(message.get("date"))
    sender = message.get("sender_name") or ""
    action = message.get("action") or {}
    media = message.get("media") or {}
    lines: list[str] = []

    prefix = f"[{date}]"
    if action:
        lines.append(f"{prefix} * {action.get('text') or action.get('type') or 'служебное сообщение'}")
    else:
        text = (message.get("text") or "").replace("\r\n", "\n").replace("\r", "\n")
        first, *rest = text.split("\n")
        lines.append(f"{prefix} {sender}: {first}".rstrip())
        for extra_line in rest:
            lines.append("    " + extra_line)

    if message.get("forwarded_from"):
        forwarded = message["forwarded_from"]
        source = forwarded.get("from_name") or forwarded.get("from_id") or forwarded.get("saved_from_peer") or "?"
        lines.append(f"    [переслано от {source}]")
    if message.get("reply_to") and message["reply_to"].get("message_id"):
        lines.append(f"    [ответ на #{message['reply_to']['message_id']}]")

    kind = media.get("kind")
    if kind:
        name = media.get("filename") or ""
        size = human_size(media.get("size")) if media.get("size") else ""
        file = media.get("file")
        error = media.get("error") or media.get("skipped")
        if kind == "poll":
            extra = media.get("extra") or {}
            lines.append(f"    [опрос] {extra.get('question') or ''}")
            for answer in extra.get("answers") or []:
                lines.append(f"      - {answer.get('text')} ({answer.get('votes', 0)})")
        elif kind == "geo":
            extra = media.get("extra") or {}
            lines.append(f"    [геолокация] {extra.get('lat')}, {extra.get('long')}")
        elif kind == "contact":
            extra = media.get("extra") or {}
            lines.append(f"    [контакт] {extra.get('first_name') or ''} {extra.get('last_name') or ''} {extra.get('phone') or ''}".rstrip())
        elif kind == "webpage":
            pass
        else:
            details = " ".join(x for x in (file or name, f"({size})" if size else "") if x)
            lines.append(f"    [{kind}] {details}" + (f" — {error}" if error else ""))

    return "\n".join(lines) + "\n"


def write_topic_index(
    chat_dir: Path,
    chat_meta: dict[str, Any],
    topics: list[dict[str, Any]],
    *,
    log=None,
) -> None:
    title = str(chat_meta.get("title") or "Чат")
    subtitle = _human_subtitle(chat_meta)
    notice = None
    if chat_meta.get("noforwards"):
        notice = ("🔒 В этом чате запрещена пересылка контента. Экспорт выполнен через ваш "
                  "собственный аккаунт, поэтому данные доступны так же, как в приложении Telegram.")
    html = [_html_head(title, subtitle, back_href="../index.html", back_label="← Все чаты", notice=notice)]
    if topics:
        html.append('<section class="topic-list" aria-label="Topics">')
        for topic in topics:
            if not topic.get("count"):
                continue
            badge = ' <span class="badge" data-ru="закреплена" data-en="pinned">закреплена</span>' if topic.get("pinned") else ""
            closed = ' <span class="badge" data-ru="закрыта" data-en="closed">закрыта</span>' if topic.get("closed") else ""
            href = quote_path(str(topic.get("dir"))) + "/messages.html"
            last_date = escape(format_datetime(topic.get("last_date")))
            topic_title = escape(str(topic.get("title") or ""))
            count = int(topic.get("count", 0))
            html.append(
                f'<a class="topic-row" href="{href}"><span class="topic-icon">{escape(str(topic.get("icon_emoji") or "●"))}</span>'
                f'<span class="topic-info"><strong>{topic_title}{badge}{closed}</strong>'
                f'<small>{last_date}</small></span><span class="topic-count">{count} сообщений · #{topic.get("id")}</span></a>'
            )
        html.append("</section>")
        html.insert(1, '<div class="notice" data-ru="Темы форума" data-en="Forum topics">Темы форума</div>')
    else:
        html.append('<div class="empty" data-ru="В этом форуме не найдено тем" data-en="No topics found">В этом форуме не найдено тем</div>')
    html.append(HTML_FOOTER)
    (chat_dir / "messages.html").write_text("".join(html), encoding="utf-8")
    if log:
        log(f"  тем в индексе: {sum(1 for t in topics if t.get('count'))}")


def render_chat_dir(
    chat_dir: Path,
    chat_meta: dict[str, Any],
    topics: list[dict[str, Any]],
    formats: set[str],
    order: str,
    *,
    log=None,
) -> None:
    chat_dir = Path(chat_dir)
    split = bool(chat_meta.get("split_topics"))
    notice = None
    if chat_meta.get("noforwards"):
        notice = ("🔒 В этом чате запрещена пересылка контента. Экспорт выполнен через ваш "
                  "собственный аккаунт, поэтому данные доступны так же, как в приложении Telegram.")

    if split and chat_meta.get("is_forum"):
        if "html" in formats:
            write_topic_index(chat_dir, chat_meta, topics, log=log)
        for topic in topics:
            if not topic.get("count"):
                continue
            source = chat_dir / str(topic.get("dir")) / "messages.jsonl"
            topic_dir = source.parent
            render_source(
                source,
                topic_dir,
                title=f"{chat_meta.get('title')} — {topic.get('title')}",
                subtitle=_human_subtitle(chat_meta, f"тема #{topic.get('id')}"),
                formats=formats,
                order=order,
                media_prefix="../../",
                back_href="../../messages.html",
                back_label="← Все темы",
                notice=notice,
                log=log,
            )
        return

    render_source(
        chat_dir / "messages.jsonl",
        chat_dir,
        title=str(chat_meta.get("title") or "Чат"),
        subtitle=_human_subtitle(chat_meta),
        formats=formats,
        order=order,
        media_prefix="",
        back_href="../index.html",
        back_label="← Все чаты",
        notice=notice,
        log=log,
    )


def update_manifest(out_root: Path, entry: dict[str, Any]) -> None:
    out_root = Path(out_root)
    manifest_path = out_root / "manifest.json"
    manifest = read_json(manifest_path) or {"chats": []}
    chats = {str(item.get("id")): item for item in manifest.get("chats", []) if isinstance(item, dict)}
    chats[str(entry.get("id"))] = entry
    manifest["chats"] = sorted(
        chats.values(),
        key=lambda item: str(item.get("updated") or ""),
        reverse=True,
    )
    manifest["generated_at"] = iso_now()
    write_json(manifest_path, manifest)
    write_root_index(out_root, manifest)


def write_root_index(out_root: Path, manifest: dict[str, Any] | None = None) -> None:
    out_root = Path(out_root)
    manifest = manifest or read_json(out_root / "manifest.json") or {"chats": []}
    chats = manifest.get("chats") or []
    html = [_html_head(
        "Экспорт Telegram",
        f"Чатов: {len(chats)} · обновлено {format_datetime(manifest.get('generated_at'))}",
    )]
    if chats:
        html.append('<table><thead><tr><th>Чат</th><th>Тип</th>'
                    '<th class="num">Сообщений</th><th class="num">Файлов</th><th>Обновлён</th></tr></thead><tbody>')
        for chat in chats:
            formats = chat.get("formats") or ["html"]
            suffix = "/messages.html" if "html" in formats else "/"
            href = quote_path(str(chat.get("dir") or "")) + suffix
            title = escape(str(chat.get("title") or "Без названия"))
            badges = ""
            if chat.get("is_forum"):
                badges += '<span class="badge">форум</span>'
            if chat.get("noforwards"):
                badges += '<span class="badge">🔒</span>'
            html.append(
                f'<tr><td><a class="topic-title" href="{href}">{title}</a>{badges}</td>'
                f'<td>{escape(_type_label(chat.get("type")))}</td>'
                f'<td class="num">{chat.get("messages", 0)}</td>'
                f'<td class="num">{chat.get("media_files", 0)}</td>'
                f'<td>{escape(format_datetime(chat.get("updated"), "%d.%m.%Y %H:%M"))}</td></tr>'
            )
        html.append("</tbody></table>")
    else:
        html.append('<div class="empty">Пока ничего не экспортировано</div>')
    html.append(HTML_FOOTER)
    (out_root / "index.html").write_text("".join(html), encoding="utf-8")
