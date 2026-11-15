"""Conversion of Telethon objects into plain JSON-friendly dictionaries."""

from __future__ import annotations

import base64
from datetime import datetime
from html import escape as html_escape
from typing import Any

from telethon import utils as tg_utils
from telethon.extensions import html as tg_html
from telethon.tl import types

from .utils import to_iso


def jsonable(value: Any, _depth: int = 0) -> Any:
    """Recursively convert Telethon objects, dates and bytes to JSON-safe data."""
    if _depth > 12:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        return {str(k): jsonable(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v, _depth + 1) for v in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return jsonable(to_dict(), _depth + 1)
        except Exception:
            pass
    return str(value)


def peer_id(peer: Any) -> int | None:
    if peer is None:
        return None
    try:
        return tg_utils.get_peer_id(peer)
    except Exception:
        value = getattr(peer, "id", None)
        return int(value) if isinstance(value, int) else None


def entity_title(entity: Any) -> str:
    try:
        title = tg_utils.get_display_name(entity)
    except Exception:
        title = None
    if title:
        return str(title)
    for attr in ("title", "first_name", "username"):
        value = getattr(entity, attr, None)
        if value:
            return str(value)
    return f"id {peer_id(entity)}"


def chat_type(entity: Any) -> str:
    if isinstance(entity, types.User):
        if getattr(entity, "is_self", False):
            return "saved"
        return "bot" if getattr(entity, "bot", False) else "user"
    if isinstance(entity, (types.Chat, types.ChatForbidden)):
        return "group"
    if isinstance(entity, types.Channel):
        return "channel" if getattr(entity, "broadcast", False) else "supergroup"
    return "unknown"


def build_chat_meta(entity: Any, *, exported_at: str | None = None) -> dict[str, Any]:
    return {
        "id": peer_id(entity),
        "title": entity_title(entity),
        "type": chat_type(entity),
        "username": getattr(entity, "username", None),
        "is_forum": bool(getattr(entity, "forum", False)),
        "noforwards": bool(getattr(entity, "noforwards", False)),
        "participants_count": getattr(entity, "participants_count", None),
        "created": to_iso(getattr(entity, "date", None)),
        "exported_at": exported_at,
    }


def build_topic_meta(topic: types.ForumTopic, *, directory: str | None = None) -> dict[str, Any]:
    return {
        "id": int(topic.id),
        "title": str(topic.title or f"Тема {topic.id}"),
        "date": to_iso(getattr(topic, "date", None)),
        "top_message": getattr(topic, "top_message", None),
        "closed": bool(getattr(topic, "closed", False)),
        "pinned": bool(getattr(topic, "pinned", False)),
        "hidden": bool(getattr(topic, "hidden", False)),
        "icon_emoji_id": getattr(topic, "icon_emoji_id", None),
        "dir": directory,
    }


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    text = getattr(value, "text", None)
    return str(text) if text is not None else str(value)


def describe_action(action: Any) -> str:
    """Short human-readable description for service messages."""
    if action is None:
        return ""
    name = type(action).__name__

    def local(field: str) -> Any:
        return getattr(action, field, None)

    if name == "MessageActionTopicCreate":
        return f"Создана тема «{_text(local('title'))}»"
    if name == "MessageActionTopicEdit":
        title = _text(local("title"))
        if title:
            return f"Тема переименована в «{title}»"
        if local("closed") is True:
            return "Тема закрыта"
        if local("closed") is False:
            return "Тема открыта"
        if local("hidden") is True:
            return "Тема скрыта"
        return "Тема изменена"
    if name in {"MessageActionChatCreate", "MessageActionChannelCreate"}:
        title = _text(local("title"))
        return f"Создан чат «{title}»" if title else "Чат создан"
    if name == "MessageActionChatEditTitle":
        return f"Чат переименован в «{_text(local('title'))}»"
    if name == "MessageActionChatAddUser":
        users = local("users") or []
        return f"Добавлены участники ({len(users)})" if users else "Добавлен участник"
    if name == "MessageActionChatDeleteUser":
        return "Участник покинул чат"
    if name == "MessageActionChatJoinedByLink":
        return "Участник присоединился по ссылке"
    if name == "MessageActionPinMessage":
        return "Закреплено сообщение"
    if name == "MessageActionHistoryClear":
        return "История очищена"
    if name == "MessageActionSetMessagesTTL":
        return f"Автоудаление сообщений: {local('period')} с"
    if name == "MessageActionPhoneCall":
        duration = local("duration")
        return f"Звонок ({duration} с)" if duration else "Звонок"
    if name == "MessageActionScreenshotTaken":
        return "Сделан скриншот"
    if name == "MessageActionChatMigrateTo":
        return "Группа преобразована в супергруппу"
    if name == "MessageActionChannelMigrateFrom":
        return "Чат преобразован в канал"
    if name == "MessageActionGroupCall":
        return "Групповой звонок"
    if name == "MessageActionGiftPremium":
        return "Подарок Premium"
    if name == "MessageActionGiveawayLaunch":
        return "Запущен розыгрыш"
    return name


def _details(action: Any) -> dict[str, Any] | None:
    if action is None:
        return None
    data = jsonable(action)
    if isinstance(data, dict):
        data.pop("_", None)
        return data
    return {"value": data}


def _forwarded(message: Any) -> dict[str, Any] | None:
    fwd = getattr(message, "fwd_from", None)
    if fwd is None:
        return None
    return {
        "from_id": peer_id(getattr(fwd, "from_id", None)),
        "from_name": getattr(fwd, "from_name", None),
        "channel_post": getattr(fwd, "channel_post", None),
        "post_author": getattr(fwd, "post_author", None),
        "date": to_iso(getattr(fwd, "date", None)),
        "saved_from_peer": peer_id(getattr(fwd, "saved_from_peer", None)),
        "saved_from_msg_id": getattr(fwd, "saved_from_msg_id", None),
    }


def _reply(message: Any) -> dict[str, Any] | None:
    reply = getattr(message, "reply_to", None)
    if reply is None:
        return None
    return {
        "message_id": getattr(reply, "reply_to_msg_id", None),
        "top_id": getattr(reply, "reply_to_top_id", None),
        "forum_topic": bool(getattr(reply, "forum_topic", False)),
        "quote_text": getattr(reply, "quote_text", None),
    }


def _reactions(message: Any) -> list[dict[str, Any]]:
    reactions = getattr(message, "reactions", None)
    results = getattr(reactions, "results", None) or []
    output: list[dict[str, Any]] = []
    for item in results:
        reaction = getattr(item, "reaction", None)
        emoji = getattr(reaction, "emoticon", None)
        if not emoji and reaction is not None:
            document_id = getattr(reaction, "document_id", None)
            if document_id:
                emoji = f"custom:{document_id}"
            elif type(reaction).__name__ == "ReactionPaid":
                emoji = "⭐"
        output.append({"emoji": emoji or "?", "count": getattr(item, "count", 0)})
    return output


def _text_and_entities(message: Any) -> tuple[str, list[dict[str, Any]], str]:
    text = getattr(message, "raw_text", None)
    if text is None:
        text = getattr(message, "message", None) or ""
    text = str(text)

    entities_raw = list(getattr(message, "entities", None) or [])
    entities = [jsonable(entity) for entity in entities_raw]
    if not text:
        return "", entities, ""
    if entities_raw:
        try:
            text_html = tg_html.unparse(text, entities_raw)
        except Exception:
            text_html = html_escape(text).replace("\n", "<br>")
    else:
        text_html = html_escape(text).replace("\n", "<br>")
    return text, entities, text_html


def message_to_dict(
    message: Any,
    chat_meta: dict[str, Any],
    *,
    topic_id: int | None = None,
    media: dict[str, Any] | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    text, entities, text_html = _text_and_entities(message)
    action = getattr(message, "action", None)

    sender = getattr(message, "sender", None)
    sender_name = entity_title(sender) if sender is not None else None
    sender_id = getattr(message, "sender_id", None)
    post_author = getattr(message, "post_author", None)
    if not sender_name:
        if getattr(message, "post", False):
            sender_name = chat_meta.get("title")
        elif post_author:
            sender_name = post_author

    result: dict[str, Any] = {
        "id": int(message.id),
        "date": to_iso(getattr(message, "date", None)),
        "type": "service" if action is not None else "message",
        "topic_id": topic_id,
        "sender_id": sender_id if sender_id is not None else (peer_id(sender) if sender is not None else None),
        "sender_name": sender_name,
        "post_author": post_author,
        "text": text,
        "text_html": text_html,
        "entities": entities,
        "reply_to": _reply(message),
        "forwarded_from": _forwarded(message),
        "grouped_id": getattr(message, "grouped_id", None),
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "reactions": _reactions(message),
        "pinned": bool(getattr(message, "pinned", False)),
        "edited": to_iso(getattr(message, "edit_date", None)),
        "noforwards": bool(getattr(message, "noforwards", False)),
        "action": None,
        "media": media,
    }

    if action is not None:
        result["action"] = {
            "type": type(action).__name__,
            "text": describe_action(action),
            "details": _details(action),
        }

    if include_raw:
        raw = getattr(message, "message", None)
        if raw is not None and hasattr(raw, "to_dict"):
            try:
                result["raw"] = jsonable(raw.to_dict())
            except Exception:
                pass

    return result
