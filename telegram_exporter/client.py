"""Telethon client creation, login and entity/folder/topic resolution."""

from __future__ import annotations

import asyncio
import platform
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from telethon import TelegramClient, errors, functions, types, utils as tg_utils

from .config import APP_VERSION, read_password
from .models import entity_title

SAVED_ALIASES = {
    "me", "self", "saved", "saved messages", "saved messages chat",
    "избранное", "избранные", "избранное сообщения", "сохранённое",
    "сохраненное", "сохранённые", "сохраненные", "мои заметки",
}

_TME_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/(?:s/)?(.+?)/?$",
    re.IGNORECASE,
)
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,31}$")


def make_client(api_id: int, api_hash: str, session: str, *, flood_threshold: int = 3600) -> TelegramClient:
    return TelegramClient(
        session,
        api_id,
        api_hash,
        device_model="Tgk Alg0rithmX",
        system_version=f"{platform.system()} {platform.release()}"[:60],
        app_version=APP_VERSION,
        lang_code="ru",
        system_lang_code="ru",
        flood_sleep_threshold=max(0, int(flood_threshold or 0)),
        timeout=30,
        request_retries=5,
        connection_retries=5,
        catch_up=False,
    )


async def _sign_in_password(client: TelegramClient, password: str | None) -> None:
    for attempt in range(3):
        value = password if attempt == 0 and password else read_password()
        try:
            await client.sign_in(password=value)
            return
        except errors.PasswordHashInvalidError:
            print("Неверный пароль. Попробуйте ещё раз.")
    raise RuntimeError("Не удалось войти: неверный пароль двухфакторной аутентификации.")


async def _phone_login(client: TelegramClient, phone: str | None, password: str | None) -> None:
    if not phone:
        phone = input("Номер телефона в формате +79991234567: ").strip()
    if not phone:
        raise RuntimeError("Номер телефона не указан.")

    try:
        sent = await client.send_code_request(phone)
    except errors.ApiIdInvalidError:
        raise RuntimeError("api_id/api_hash неверны. Проверьте их на https://my.telegram.org.")
    except errors.PhoneNumberInvalidError:
        raise RuntimeError("Telegram не принял номер телефона. Проверьте формат (+код страны...).")
    except errors.PhoneNumberBannedError:
        raise RuntimeError("Этот номер заблокирован в Telegram.")
    except errors.FloodWaitError as exc:
        raise RuntimeError(f"Telegram просит подождать {exc.seconds} секунд перед повторной попыткой.")

    print(f"Код отправлен в Telegram на {phone}. Он может прийти в приложение, SMS или звонком.")

    for _ in range(3):
        code = input("Код подтверждения: ").strip().replace(" ", "").replace("-", "")
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
            return
        except errors.SessionPasswordNeededError:
            await _sign_in_password(client, password)
            return
        except errors.PhoneCodeInvalidError:
            print("Неверный код, попробуйте снова.")
        except errors.PhoneCodeExpiredError:
            print("Код истёк, отправляю новый.")
            sent = await client.send_code_request(phone)
        except errors.FloodWaitError as exc:
            raise RuntimeError(f"Слишком много попыток. Подождите {exc.seconds} секунд.")

    raise RuntimeError("Не удалось ввести код подтверждения.")


def _print_qr(url: str) -> None:
    """Print a scannable QR code if the optional qrcode package is installed."""
    try:
        import qrcode
    except ImportError:
        print("Для QR-кода в консоли установите пакет: python -m pip install qrcode")
        print(url)
        return

    code = qrcode.QRCode(border=3)
    code.add_data(url)
    code.make(fit=True)
    matrix = code.get_matrix()
    black = "\x1b[40m  "
    white = "\x1b[47m  "
    for row in matrix:
        print("".join(black if cell else white for cell in row) + "\x1b[0m")
    print()
    print("Если QR не читается, можно открыть эту ссылку на телефоне:")
    print(url)


async def _qr_login(client: TelegramClient, password: str | None) -> None:
    print("Откройте Telegram на телефоне:")
    print("  Настройки → Устройства → Подключить устройство → Отсканируйте QR-код")
    print("(или в веб-версии: Настройки → Devices → Link Desktop Device)")
    print()

    qr = await client.qr_login()
    _print_qr(qr.url)

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            await qr.wait(timeout=25)
            return
        except asyncio.TimeoutError:
            try:
                await qr.recreate()
                print("QR-код обновлён:")
                _print_qr(qr.url)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Не удалось обновить QR-код: {exc}")
        except errors.SessionPasswordNeededError:
            await _sign_in_password(client, password)
            return

    raise RuntimeError("Время ожидания QR-кода истекло. Запустите login ещё раз.")


async def ensure_authorized(
    client: TelegramClient,
    *,
    phone: str | None = None,
    qr: bool = False,
    password: str | None = None,
    interactive: bool = True,
) -> bool:
    await client.connect()
    if await client.is_user_authorized():
        return True
    if not interactive:
        return False

    if qr:
        await _qr_login(client, password)
    else:
        await _phone_login(client, phone, password)

    if not await client.is_user_authorized():
        raise RuntimeError("Авторизация не завершена.")
    return True


def parse_ref(raw: str) -> tuple[str, Any]:
    """Parse user input into a peer/username/id/title reference."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Пустая ссылка на чат.")

    if text.casefold() in SAVED_ALIASES:
        return "saved", None

    if text.startswith("tg://"):
        parsed = urlparse(text)
        values = parse_qs(parsed.query)
        domain = (values.get("domain") or [None])[0]
        if domain:
            return "username", domain
        raise ValueError("Поддерживаются только tg://resolve?domain=... ссылки.")

    match = _TME_RE.match(text)
    if match:
        rest = match.group(1).strip("/")
        parts = [part for part in rest.split("/") if part]
        if not parts:
            raise ValueError("Не удалось разобрать ссылку t.me.")
        if parts[0] == "c" and len(parts) >= 2 and parts[1].isdigit():
            return "peer", types.PeerChannel(int(parts[1]))
        if parts[0].startswith("+") or parts[0] == "joinchat":
            raise ValueError(
                "Это инвайт-ссылка. Экспортировать можно только чаты, в которых вы уже состоите.\n"
                "Вступите в чат, затем найдите его через `list` или по точному названию."
            )
        if parts[0].isdigit():
            return "peer", types.PeerChannel(int(parts[0]))
        return "username", parts[0]

    if text.startswith("@"):
        return "username", text[1:]

    if re.fullmatch(r"-?\d+", text):
        number = int(text)
        if number < 0:
            digits = str(-number)
            if digits.startswith("100") and len(digits) > 3:
                return "peer", types.PeerChannel(int(digits[3:]))
            return "peer", types.PeerChat(-number)
        return "id", number

    if _USERNAME_RE.match(text):
        return "username", text

    return "title", text


class Resolver:
    """Resolve chats, folders (chat filters) and forum topics."""

    def __init__(self, client: TelegramClient) -> None:
        self.client = client
        self._dialogs: list[Any] | None = None

    async def dialogs(self, refresh: bool = False) -> list[Any]:
        if self._dialogs is None or refresh:
            result = []
            async for dialog in self.client.iter_dialogs():
                result.append(dialog)
            self._dialogs = result
        return self._dialogs

    async def resolve(self, raw: str) -> Any:
        kind, value = parse_ref(raw)

        if kind == "saved":
            return await self.client.get_entity("me")

        if kind == "peer":
            try:
                return await self.client.get_entity(value)
            except Exception:
                pass
            entity = await self._entity_from_dialogs(tg_utils.get_peer_id(value))
            if entity is not None:
                return entity
            raise LookupError(
                f"Не нашёл чат {raw!r} в ваших диалогах. "
                "Выполните `list`, чтобы увидеть доступные чаты, или используйте @username/ссылку."
            )

        if kind == "id":
            # Positive IDs are ambiguous: they can be user IDs or the internal
            # ID of a group/channel. Prefer chats already present in dialogs.
            entity = await self._entity_from_dialogs(value)
            if entity is not None:
                return entity
            try:
                return await self.client.get_entity(types.PeerUser(value))
            except Exception:
                pass
            raise LookupError(
                f"Не удалось найти чат с id {value}. Выполните `list` и используйте "
                "точный id/название/@username."
            )

        if kind == "username":
            try:
                return await self.client.get_entity(value)
            except Exception:
                pass

        return await self._resolve_by_title(raw)

    async def _entity_from_dialogs(self, wanted_id: int | None) -> Any | None:
        if wanted_id is None:
            return None
        for dialog in await self.dialogs():
            if dialog.id == wanted_id:
                return dialog.entity
            # A positive value may be the raw Telegram ID of a group/channel;
            # Telethon represents the same dialog with a marked negative ID.
            if wanted_id > 0 and getattr(dialog.entity, "id", None) == wanted_id:
                return dialog.entity
        return None

    async def _resolve_by_title(self, raw: str) -> Any:
        needle = raw.casefold().strip()
        dialogs = await self.dialogs()
        exact = [d for d in dialogs if (d.title or "").casefold() == needle]
        if not exact:
            exact = [d for d in dialogs if needle and needle in (d.title or "").casefold()]
        if not exact:
            exact = [
                d for d in dialogs
                if (getattr(d.entity, "username", None) or "").casefold() == needle.lstrip("@")
            ]
        if len(exact) == 1:
            return exact[0].entity
        if len(exact) > 1:
            names = "\n".join(f"  {d.id}: {d.title}" for d in exact[:15])
            raise LookupError(
                f"Найдено несколько чатов по запросу {raw!r}:\n{names}\n"
                "Укажите id или @username, чтобы выбрать один."
            )
        raise LookupError(
            f"Чат {raw!r} не найден. Выполните `list`, чтобы увидеть доступные чаты."
        )

    async def filters(self) -> list[dict[str, Any]]:
        result = await self.client(functions.messages.GetDialogFiltersRequest())
        output: list[dict[str, Any]] = []
        for item in getattr(result, "filters", None) or []:
            if isinstance(item, types.DialogFilterDefault):
                continue
            title = getattr(item, "title", "")
            if not isinstance(title, str):
                title = str(getattr(title, "text", title))
            include = list(getattr(item, "include_peers", None) or [])
            pinned = list(getattr(item, "pinned_peers", None) or [])
            output.append({
                "id": getattr(item, "id", None),
                "title": title,
                "include": include,
                "pinned": pinned,
                "raw": item,
                "chatlist": isinstance(item, types.DialogFilterChatlist),
            })
        return output

    async def resolve_folder(self, name: str) -> list[Any]:
        name = str(name).strip()
        if name.casefold() in {"archive", "архив"} or name == "1":
            return [dialog.entity for dialog in await self.dialogs() if getattr(dialog, "archived", False)]

        filters = await self.filters()
        if not filters:
            raise LookupError("У вас нет папок (разделов) в Telegram.")

        match: dict[str, Any] | None = None
        if name.isdigit():
            match = next((f for f in filters if str(f["id"]) == name), None)
        if match is None:
            match = next((f for f in filters if f["title"].casefold() == name.casefold()), None)
        if match is None:
            partial = [f for f in filters if name.casefold() in f["title"].casefold()]
            if len(partial) == 1:
                match = partial[0]
            elif len(partial) > 1:
                names = "\n".join(f"  {f['id']}: {f['title']}" for f in partial)
                raise LookupError(f"Несколько папок совпадают с {name!r}:\n{names}")
        if match is None:
            names = "\n".join(f"  {f['id']}: {f['title']}" for f in filters)
            raise LookupError(f"Папка {name!r} не найдена. Доступные папки:\n{names}")

        return await self._entities_for_filter(match["raw"])

    async def _entities_for_filter(self, item: Any) -> list[Any]:
        exclude_ids = {
            tg_utils.get_peer_id(peer)
            for peer in (getattr(item, "exclude_peers", None) or [])
        }
        include = list(getattr(item, "include_peers", None) or [])
        include += list(getattr(item, "pinned_peers", None) or [])

        entities: list[Any] = []
        for peer in include:
            try:
                entity = await self.client.get_entity(peer)
            except Exception:
                continue
            if tg_utils.get_peer_id(entity) not in exclude_ids:
                entities.append(entity)

        # Telegram folders can combine explicitly included peers with categories
        # (groups, contacts, channels, etc.). Include both sets, then de-duplicate.
        category_flags = (
            "contacts", "non_contacts", "groups", "broadcasts", "bots",
            "exclude_muted", "exclude_read", "exclude_archived",
        )
        if any(getattr(item, flag, False) for flag in category_flags):
            for dialog in await self.dialogs():
                if dialog.id in exclude_ids:
                    continue
                if self._matches_filter(dialog, item):
                    entities.append(dialog.entity)

        return _dedupe_entities(entities)

    @staticmethod
    def _matches_filter(dialog: Any, item: Any) -> bool:
        entity = dialog.entity
        is_user = isinstance(entity, types.User)
        is_group = isinstance(entity, types.Chat) or (
            isinstance(entity, types.Channel) and bool(getattr(entity, "megagroup", False))
        )
        is_broadcast = isinstance(entity, types.Channel) and bool(getattr(entity, "broadcast", False))

        flags = {name: getattr(item, name, None) for name in
                 ("contacts", "non_contacts", "groups", "broadcasts", "bots")}
        if any(flags.values()):
            if is_user:
                if getattr(entity, "bot", False):
                    allowed = bool(flags["bots"])
                elif getattr(entity, "contact", False):
                    allowed = bool(flags["contacts"])
                else:
                    allowed = bool(flags["non_contacts"])
            elif is_group:
                allowed = bool(flags["groups"])
            elif is_broadcast:
                allowed = bool(flags["broadcasts"])
            else:
                allowed = False
            if not allowed:
                return False

        if getattr(item, "exclude_muted", False):
            notify = getattr(getattr(dialog, "dialog", None), "notify_settings", None)
            mute_until = getattr(notify, "mute_until", None)
            if mute_until:
                try:
                    if mute_until.timestamp() > time.time():
                        return False
                except (OSError, ValueError, OverflowError):
                    pass

        if getattr(item, "exclude_read", False) and not getattr(dialog, "unread_count", 0):
            return False

        if getattr(item, "exclude_archived", False) and getattr(dialog, "archived", False):
            return False

        return True

    async def topics(self, entity: Any, limit: int = 100) -> list[types.ForumTopic]:
        if not getattr(entity, "forum", False):
            return []
        input_entity = await self.client.get_input_entity(entity)
        output: list[types.ForumTopic] = []
        seen: set[int] = set()
        offset_topic = 0

        while True:
            try:
                result = await self.client(functions.channels.GetForumTopicsRequest(
                    channel=input_entity,
                    offset_date=None,
                    offset_id=0,
                    offset_topic=offset_topic,
                    limit=limit,
                    q=None,
                ))
            except errors.ChannelForumMissingError:
                return output
            except errors.RPCError:
                return output

            topics = list(getattr(result, "topics", None) or [])
            added = 0
            for topic in topics:
                if isinstance(topic, types.ForumTopic) and topic.id not in seen:
                    seen.add(topic.id)
                    output.append(topic)
                    added += 1
            if len(topics) < limit or added == 0:
                break
            offset_topic = topics[-1].id

        output.sort(key=lambda topic: topic.id)
        return output


def _dedupe_entities(entities: list[Any]) -> list[Any]:
    seen: set[int] = set()
    output: list[Any] = []
    for entity in entities:
        try:
            key = tg_utils.get_peer_id(entity)
        except Exception:
            key = id(entity)
        if key in seen:
            continue
        seen.add(key)
        output.append(entity)
    return output


def dialog_line(dialog: Any, folder_names: dict[int, str] | None = None) -> str:
    """One-line description used by the list command."""
    folder_names = folder_names or {}
    entity = dialog.entity
    title = entity_title(entity)
    if len(title) > 44:
        title = title[:41] + "..."
    username = getattr(entity, "username", None)
    username_text = f"@{username}" if username else ""
    type_name = dialog_type(entity)
    folder = ""
    raw_dialog = getattr(dialog, "dialog", None)
    folder_id = getattr(raw_dialog, "folder_id", None)
    if folder_id is not None:
        folder = folder_names.get(folder_id) or str(folder_id)
        if len(folder) > 12:
            folder = folder[:11] + "~"
    forum = "yes" if getattr(entity, "forum", False) else ""
    protected = "prot" if getattr(entity, "noforwards", False) else ""
    return (
        f"{dialog.id:>15}  {type_name:<10}  {title:<44}  "
        f"{username_text:<20}  {folder:<12}  {forum:<5} {protected}"
    )


def dialog_type(entity: Any) -> str:
    if isinstance(entity, types.User):
        if getattr(entity, "is_self", False):
            return "saved"
        return "bot" if getattr(entity, "bot", False) else "user"
    if isinstance(entity, types.Chat):
        return "group"
    if isinstance(entity, types.Channel):
        return "channel" if getattr(entity, "broadcast", False) else "supergroup"
    return "unknown"


async def print_dialogs(
    resolver: Resolver,
    *,
    search: str | None = None,
    type_filter: str | None = None,
    limit: int | None = None,
) -> None:
    dialogs = await resolver.dialogs()
    folder_names: dict[int, str] = {1: "Архив"}
    try:
        for item in await resolver.filters():
            if item.get("id") is not None:
                folder_names[int(item["id"])] = str(item.get("title") or item["id"])
    except Exception:
        pass

    shown = 0
    print(f"{'ID':>15}  {'TYPE':<10}  {'TITLE':<44}  {'USERNAME':<20}  {'FOLDER':<12}  FORUM")
    print("-" * 124)
    for dialog in dialogs:
        type_name = dialog_type(dialog.entity)
        if type_filter and type_name != type_filter:
            continue
        haystack = f"{dialog.title} {getattr(dialog.entity, 'username', '') or ''}".casefold()
        if search and search.casefold() not in haystack:
            continue
        print(dialog_line(dialog, folder_names))
        shown += 1
        if limit and shown >= limit:
            break
    print("-" * 124)
    print(f"Показано: {shown} из {len(dialogs)}")
