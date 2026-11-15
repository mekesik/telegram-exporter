"""Command line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from telethon import errors, utils as tg_utils

from . import __version__
from .client import (
    Resolver,
    dialog_type,
    ensure_authorized,
    make_client,
    print_dialogs,
)
from .config import (
    APP_VERSION,
    config_path,
    load_config,
    resolve_credentials,
    resolve_session_path,
)
from .exporter import Exporter
from .media import DOWNLOADABLE
from .models import build_topic_meta, entity_title
from .notifier import BotNotifier, bot_settings, detect_chat_id
from .render import render_chat_dir, write_root_index
from .reset import reset_export
from .utils import format_datetime, parse_datetime, parse_size, read_json, write_json

ALL_FORMATS = {"html", "txt", "csv", "json"}
ALL_MEDIA_TYPES = set(DOWNLOADABLE)
DIALOG_TYPES = ("user", "bot", "group", "supergroup", "channel", "saved")


def parse_formats(value: str) -> set[str]:
    value = (value or "html").strip().lower()
    if value in {"all", "*"}:
        return set(ALL_FORMATS)
    formats = {part.strip() for part in value.split(",") if part.strip()}
    unknown = formats - ALL_FORMATS
    if unknown:
        raise SystemExit(
            f"Неизвестный формат: {', '.join(sorted(unknown))}. "
            f"Доступно: {', '.join(sorted(ALL_FORMATS))} или all."
        )
    return formats or {"html"}


def parse_media_types(value: str) -> set[str]:
    value = (value or "all").strip().lower()
    if value in {"all", "*"}:
        return set(ALL_MEDIA_TYPES)
    types = {part.strip() for part in value.split(",") if part.strip()}
    unknown = types - ALL_MEDIA_TYPES
    if unknown:
        raise SystemExit(
            f"Неизвестный тип медиа: {', '.join(sorted(unknown))}. "
            f"Доступно: {', '.join(sorted(ALL_MEDIA_TYPES))} или all."
        )
    return types


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-id", type=int, help="api_id с my.telegram.org")
    common.add_argument("--api-hash", help="api_hash с my.telegram.org")
    common.add_argument("--session", help="имя или путь файла сессии (по умолчанию 'default')")
    common.add_argument(
        "--flood-threshold", type=int, default=3600,
        help="сколько секунд автоматически ждать при FloodWait (по умолчанию 3600)",
    )
    common.add_argument("-v", "--verbose", action="store_true", help="подробный вывод и логи Telethon")

    parser = argparse.ArgumentParser(
        prog="telegram-exporter",
        description="Экспорт чатов, каналов, папок и форумов Telegram через ваш аккаунт (MTProto).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", parents=[common], help="войти в аккаунт и сохранить сессию")
    login.add_argument("--qr", action="store_true", help="вход по QR-коду вместо кода из сообщения")
    login.add_argument("--phone", help="номер телефона, если не хотите вводить его вручную")

    sub.add_parser("logout", parents=[common], help="выйти и удалить локальную сессию")
    info = sub.add_parser("info", parents=[common], help="показать состояние сессии и аккаунта")
    info.set_defaults()

    lst = sub.add_parser("list", parents=[common], help="список чатов и каналов")
    lst.add_argument("--search", help="фильтр по названию/username")
    lst.add_argument("--type", choices=DIALOG_TYPES, help="фильтр по типу")
    lst.add_argument("--limit", type=int, help="показать не больше N строк")
    lst.add_argument("--json", action="store_true", help="вывести JSON")

    folders = sub.add_parser("folders", parents=[common], help="список папок (разделов) Telegram")
    folders.add_argument("--json", action="store_true", help="вывести JSON")

    topics = sub.add_parser("topics", parents=[common], help="список тем форума")
    topics.add_argument("chat", help="чат: id, @username, ссылка или название")
    topics.add_argument("--json", action="store_true", help="вывести JSON")

    export = sub.add_parser("export", parents=[common], help="экспортировать чаты")
    export.add_argument("chats", nargs="*", help="чаты: id, @username, ссылка или название")
    export.add_argument("-o", "--out", default="exports", help="папка для экспорта (по умолчанию exports)")
    export.add_argument("--all", dest="all_dialogs", action="store_true", help="экспортировать все диалоги")
    export.add_argument("--folder", action="append", default=[], help="экспортировать папку (можно несколько)")
    export.add_argument("--type", action="append", default=[], choices=DIALOG_TYPES,
                        help="ограничить типы чатов")
    export.add_argument("--format", default="html",
                        help="форматы: html,txt,csv,json,all (по умолчанию html; jsonl пишется всегда)")
    export.add_argument("--media", dest="download_media", action="store_true", default=True,
                        help="скачивать медиа (по умолчанию)")
    export.add_argument("--no-media", dest="download_media", action="store_false",
                        help="не скачивать файлы, только метаданные")
    export.add_argument("--media-types", default="all",
                        help="какие типы скачивать: photo,video,round,voice,audio,sticker,gif,file или all")
    export.add_argument("--max-media-size", default="0",
                        help="максимальный размер файла, например 500MB (0 = без лимита)")
    export.add_argument("--since", help="с даты (2024-01-31, 31.01.2024, 2024-01-31T12:30)")
    export.add_argument("--until", help="по дату включительно")
    export.add_argument("--limit", type=int, help="максимум сообщений на чат (последние N)")
    export.add_argument("--incremental", action="store_true",
                        help="докачивать только новые сообщения с прошлого запуска")
    export.add_argument("--no-split-topics", dest="split_topics", action="store_false", default=True,
                        help="не разбивать форум на отдельные темы")
    export.add_argument("--wait-time", type=float, default=None,
                        help="пауза между запросами истории, сек (Telegram сам ставит при больших объёмах)")
    export.add_argument("--raw", action="store_true", help="добавить в JSONL сырые данные сообщений")
    export.add_argument("--quiet", action="store_true", help="меньше вывода")
    export.add_argument("--bot-token", help="токен бота для уведомлений (иначе config.json или TELEGRAM_BOT_TOKEN)")
    export.add_argument("--bot-chat", help="chat_id получателя уведомлений (иначе config.json или TELEGRAM_BOT_CHAT_ID)")
    export.add_argument("--bot-every", type=float, default=None,
                        help="как часто присылать прогресс, сек (по умолчанию 60)")
    export.add_argument("--no-bot", action="store_true", help="не отправлять уведомления боту")

    bot = sub.add_parser("bot", help="настроить бота, который пишет, что скачано и что осталось")
    bot.add_argument("--token", help="токен бота от @BotFather")
    bot.add_argument("--chat", help="chat_id получателя (можно узнать через --detect)")
    bot.add_argument("--detect", action="store_true",
                     help="определить chat_id по последнему сообщению боту (нажмите /start)")
    bot.add_argument("--test", action="store_true", help="отправить тестовое сообщение")
    bot.add_argument("--every", type=float, help="интервал отчётов о прогрессе, сек (60 по умолчанию)")
    bot.add_argument("--clear", action="store_true", help="удалить настройки бота")

    reset = sub.add_parser("reset", help="очистить сообщения и медиа, сохранив метаданные и дату экспорта")
    reset.add_argument("path", nargs="?", default="exports", help="папка экспорта")
    reset.add_argument("--yes", action="store_true", help="подтвердить очистку без вопроса")

    render = sub.add_parser("render", help="перегенерировать HTML/TXT/CSV/JSON из готовых JSONL")
    render.add_argument("path", help="папка экспорта или конкретный чат")
    render.add_argument("--format", default="all", help="html,txt,csv,json,all")

    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
        format="%(message)s",
    )
    logging.getLogger("telethon").setLevel(
        logging.INFO if getattr(args, "verbose", False) else logging.WARNING
    )

    try:
        if args.command == "bot":
            return bot_command(args)
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n[!] Прервано. Частичные данные сохранены, для продолжения используйте --incremental.")
        return 130
    except LookupError as exc:
        print(f"[!] {exc}")
        return 1
    except errors.FloodWaitError as exc:
        print(f"[!] Telegram просит подождать {exc.seconds} секунд. Запустите позже.")
        return 1
    except RuntimeError as exc:
        print(f"[!] {exc}")
        return 1
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[!] Ошибка: {type(exc).__name__}: {exc}")
        if getattr(args, "verbose", False):
            traceback.print_exc()
        return 1


async def run(args: argparse.Namespace) -> int:
    if args.command == "render":
        return render_command(args)
    if args.command == "reset":
        return reset_command(args)
    if args.command == "info":
        return await info_command(args)
    if args.command == "export" and not args.chats and not args.folder and not args.all_dialogs:
        raise SystemExit(
            "Нечего экспортировать. Укажите чат (id/@username/ссылка/название), "
            "--folder \"Название папки\" или --all."
        )

    cfg = load_config()
    api_id, api_hash = resolve_credentials(args.api_id, args.api_hash, interactive=True)
    session = resolve_session_path(args.session, cfg)
    client = make_client(api_id, api_hash, session, flood_threshold=args.flood_threshold)

    try:
        await client.connect()

        if args.command == "logout":
            if await client.is_user_authorized():
                await client.log_out()
            for suffix in (".session", ".session-journal"):
                path = Path(session + suffix)
                if path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass
            print("Вы вышли из аккаунта, локальная сессия удалена.")
            return 0

        authorized = await ensure_authorized(
            client,
            phone=getattr(args, "phone", None),
            qr=getattr(args, "qr", False),
            interactive=True,
        )
        if not authorized:
            print("[!] Не удалось авторизоваться.")
            return 1

        me = await client.get_me()
        if args.command == "login":
            print()
            print(f"Готово. Вы вошли как {entity_title(me)}"
                  f"{' (@' + me.username + ')' if getattr(me, 'username', None) else ''}, id {me.id}.")
            print(f"Сессия: {session}.session")
            print("Файл сессии даёт полный доступ к аккаунту - не передавайте его никому.")
            return 0

        resolver = Resolver(client)

        if args.command == "list":
            if args.json:
                dialogs = await resolver.dialogs()
                payload = []
                for dialog in dialogs:
                    type_name = dialog_type(dialog.entity)
                    if args.type and type_name != args.type:
                        continue
                    haystack = f"{dialog.title} {getattr(dialog.entity, 'username', '') or ''}".casefold()
                    if args.search and args.search.casefold() not in haystack:
                        continue
                    raw_dialog = getattr(dialog, "dialog", None)
                    payload.append({
                        "id": dialog.id,
                        "title": dialog.title,
                        "type": type_name,
                        "username": getattr(dialog.entity, "username", None),
                        "forum": bool(getattr(dialog.entity, "forum", False)),
                        "noforwards": bool(getattr(dialog.entity, "noforwards", False)),
                        "folder_id": getattr(raw_dialog, "folder_id", None),
                        "unread": getattr(dialog, "unread_count", 0),
                    })
                    if args.limit and len(payload) >= args.limit:
                        break
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                await print_dialogs(
                    resolver,
                    search=args.search,
                    type_filter=args.type,
                    limit=args.limit,
                )
            return 0

        if args.command == "folders":
            filters = await resolver.filters()
            rows = []
            dialogs = await resolver.dialogs()
            rows.append({
                "id": 1,
                "title": "Архив",
                "peers": sum(1 for dialog in dialogs if getattr(dialog, "archived", False)),
                "flags": ["archive"],
                "chatlist": False,
            })
            for item in filters:
                peers = {tg_utils.get_peer_id(peer) for peer in item["include"] + item["pinned"]}
                flags = [
                    name for name in ("contacts", "non_contacts", "groups", "broadcasts", "bots")
                    if getattr(item["raw"], name, None)
                ]
                flags += [
                    name for name in ("exclude_muted", "exclude_read", "exclude_archived")
                    if getattr(item["raw"], name, False)
                ]
                rows.append({
                    "id": item["id"],
                    "title": item["title"],
                    "peers": len(peers),
                    "flags": flags,
                    "chatlist": item["chatlist"],
                })
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                print(f"{'ID':>4}  {'НАЗВАНИЕ':<32}  {'ЧАТОВ':>6}  ФЛАГИ")
                print("-" * 78)
                for row in rows:
                    title = row["title"][:32]
                    print(f"{str(row['id']):>4}  {title:<32}  {row['peers']:>6}  {', '.join(row['flags'])}")
                print("-" * 78)
                print(f"Всего папок: {len(rows)}")
            return 0

        if args.command == "topics":
            entity = await resolver.resolve(args.chat)
            if not getattr(entity, "forum", False):
                print("Этот чат не является форумом (в нём нет тем).")
                return 0
            found = await resolver.topics(entity)
            payload = [{
                "id": 1,
                "title": "General",
                "pinned": False,
                "closed": False,
                "top_message": 1,
                "date": None,
            }]
            for topic in found:
                meta = build_topic_meta(topic)
                payload.append({
                    "id": meta["id"],
                    "title": meta["title"],
                    "pinned": meta["pinned"],
                    "closed": meta["closed"],
                    "top_message": meta["top_message"],
                    "date": meta["date"],
                })
            payload.sort(key=lambda row: row["id"])
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"{'ID':>6}  {'ТЕМА':<46}  {'ЗАКРЕП':<7}  {'ЗАКРЫТА':<8}  TOP")
                print("-" * 82)
                for row in payload:
                    title = row["title"][:46]
                    print(f"{row['id']:>6}  {title:<46}  "
                          f"{'да' if row['pinned'] else '':<7}  "
                          f"{'да' if row['closed'] else '':<8}  {row['top_message']}")
                print("-" * 82)
                print(f"Всего тем: {len(payload)}")
            return 0

        if args.command == "export":
            return await export_command(args, client, resolver)

        print(f"Неизвестная команда: {args.command}")
        return 2
    finally:
        await client.disconnect()


def bot_command(args: argparse.Namespace) -> int:
    cfg = load_config()

    if args.clear:
        changed = False
        for key in ("bot_token", "bot_chat_id", "bot_every"):
            if key in cfg:
                cfg.pop(key, None)
                changed = True
        if changed:
            write_json(config_path(), cfg)
        print("[i] Настройки бота удалены. Уведомления больше не отправляются.")
        if os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_CHAT_ID"):
            print("    Переменные TELEGRAM_BOT_TOKEN / TELEGRAM_BOT_CHAT_ID всё ещё заданы —")
            print("    удалите их из окружения, если бот больше не нужен.")
        return 0

    if args.every is not None and args.every <= 0:
        print("[!] --every должен быть больше нуля.")
        return 1

    if args.token:
        cfg["bot_token"] = args.token.strip()
    if args.chat:
        cfg["bot_chat_id"] = str(args.chat).strip()
    if args.every is not None:
        cfg["bot_every"] = float(args.every)

    token, chat_id = bot_settings(cfg)

    if args.detect:
        if not token:
            print("[!] Сначала укажите токен: bot --token <токен> --detect")
            return 1
        found = detect_chat_id(token)
        if not found:
            print("[!] Не нашёл сообщений боту. Откройте бота в Telegram, нажмите /start")
            print("    и повторите: python -m telegram_exporter bot --detect")
            return 1
        cfg["bot_chat_id"] = found
        chat_id = found
        print(f"[i] chat_id определён: {chat_id}")

    if args.token or args.chat or args.detect or args.every is not None:
        write_json(config_path(), cfg)

    token, chat_id = bot_settings(cfg)
    interval = cfg.get("bot_every") or 60

    print(f"config:   {config_path()}")
    print(f"токен:    {'задан' if token else 'нет'}")
    print(f"chat_id:  {chat_id or 'нет'}")
    print(f"интервал: {interval} с")

    if args.test:
        if not (token and chat_id):
            print("[!] Для теста нужны токен и chat_id.")
            return 1
        notifier = BotNotifier(token, chat_id)
        ok = asyncio.run(notifier.send(
            "✅ <b>Проверка связи</b>\n"
            "Бот готов присылать отчёты: что скачано и что осталось."
        ))
        if ok:
            print("[i] Тестовое сообщение отправлено.")
        else:
            print(f"[!] Не удалось отправить: {notifier.last_error or 'неизвестная ошибка'}")
            return 1

    if not token or not chat_id:
        print()
        print("Как включить уведомления:")
        print("  1. Создайте бота у @BotFather и скопируйте токен.")
        print("  2. Откройте бота в Telegram и нажмите /start.")
        print("  3. Выполните: python -m telegram_exporter bot --token <токен> --detect")
        print("  4. Проверка:   python -m telegram_exporter bot --test")
    return 0


def reset_command(args: argparse.Namespace) -> int:
    try:
        reset_export(Path(args.path), confirmed=args.yes)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[!] {exc}")
        return 1
    return 0


async def export_command(args: argparse.Namespace, client: Any, resolver: Resolver) -> int:
    targets: list[Any] = []
    seen: set[int] = set()

    def add(entity: Any) -> None:
        try:
            key = tg_utils.get_peer_id(entity)
        except Exception:
            key = id(entity)
        if key not in seen:
            seen.add(key)
            targets.append(entity)

    for ref in args.chats:
        add(await resolver.resolve(ref))

    for folder in args.folder:
        found = await resolver.resolve_folder(folder)
        print(f"[i] Папка {folder!r}: чатов {len(found)}")
        for entity in found:
            add(entity)

    if args.all_dialogs:
        for dialog in await resolver.dialogs():
            add(dialog.entity)

    if args.type:
        allowed = set(args.type)
        targets = [entity for entity in targets if dialog_type(entity) in allowed]

    if not targets:
        raise SystemExit(
            "Нечего экспортировать. Укажите чат (id/@username/ссылка/название), "
            "--folder \"Название папки\" или --all."
        )

    try:
        since = parse_datetime(args.since)
        until = parse_datetime(args.until, end_of_day=True)
        max_media_size = parse_size(args.max_media_size)
    except ValueError as exc:
        raise SystemExit(str(exc))

    if since and until and since > until:
        raise SystemExit("--since позже --until. Проверьте даты.")

    formats = parse_formats(args.format)
    media_types = parse_media_types(args.media_types)
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit должен быть положительным числом.")

    out_root = Path(args.out).expanduser()
    out_root.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    notifier: BotNotifier | None = None
    try:
        bot_every = float(cfg.get("bot_every") or 60)
    except (TypeError, ValueError):
        bot_every = 60.0
    if args.bot_every is not None:
        bot_every = args.bot_every
    if not args.no_bot:
        if bot_every <= 0:
            raise SystemExit("--bot-every должен быть больше нуля.")
        token, chat_id = bot_settings(cfg, args.bot_token, args.bot_chat)
        if token and chat_id:
            notifier = BotNotifier(token, chat_id)
        elif args.bot_token or args.bot_chat:
            print("[!] Для уведомлений нужны и токен, и chat_id. Экспорт пойдёт без бота.")

    print(f"[i] Чатов к экспорту: {len(targets)}")
    print(f"[i] Папка: {out_root.resolve()}")
    print(f"[i] Форматы: {', '.join(sorted(formats))} + jsonl")
    print(f"[i] Медиа: {'да' if args.download_media else 'нет'}"
          f"{' (типы: ' + ', '.join(sorted(media_types)) + ')' if args.download_media else ''}")
    if args.incremental:
        print("[i] Режим: докачивать новое (--incremental)")
    if since or until:
        print(f"[i] Период: {format_datetime(since, '%d.%m.%Y') if since else '...'} - "
              f"{format_datetime(until, '%d.%m.%Y') if until else '...'}")
    if args.limit:
        print(f"[i] Лимит: последние {args.limit} сообщений на чат")
    if notifier is not None:
        print(f"[i] Бот-уведомления: включены (прогресс каждые {int(bot_every)} с)")
    elif not args.no_bot:
        print("[i] Бот-уведомления: выключены (настройте командой `bot`)")

    exporter = Exporter(
        client,
        resolver,
        out_root,
        formats=formats,
        download_media=args.download_media,
        media_types=media_types,
        max_media_size=max_media_size,
        since=since,
        until=until,
        limit=args.limit,
        incremental=args.incremental,
        split_topics=args.split_topics,
        wait_time=args.wait_time,
        include_raw=args.raw,
        quiet=args.quiet,
        notifier=notifier,
        bot_every=bot_every,
    )
    failures = await exporter.export_entities(targets)

    print()
    print(f"Готово. Чатов: {len(targets)}, ошибок: {failures}, сообщений добавлено: {exporter.fetched_total}")
    if notifier is not None:
        if notifier.last_error:
            print(f"[!] Бот: последняя ошибка - {notifier.last_error}")
        else:
            print(f"[i] Бот: отправлено сообщений {notifier.sent}")
    print(f"Открыть: {(out_root / 'index.html').resolve()}")
    return 1 if failures else 0


def render_command(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser()
    if not path.exists():
        print(f"[!] Папка не найдена: {path}")
        return 1

    formats = parse_formats(args.format)
    is_chat_dir = (path / "chat.json").exists()
    if is_chat_dir:
        dirs = [path]
        out_root = path.parent
    else:
        dirs = [child for child in path.iterdir() if child.is_dir() and (child / "chat.json").exists()]
        out_root = path

    if not dirs:
        print("[!] Не найдено ни одного экспортированного чата (chat.json).")
        return 1

    for chat_dir in dirs:
        chat = read_json(chat_dir / "chat.json") or {}
        topics_data = read_json(chat_dir / "topics.json") or {}
        topics = topics_data.get("topics") or []
        print(f"[i] {chat.get('title') or chat_dir.name}")
        render_chat_dir(
            chat_dir,
            chat,
            topics,
            formats,
            chat.get("order", "asc"),
            log=print,
        )

    if (out_root / "manifest.json").exists():
        write_root_index(out_root)
    print("Готово.")
    return 0


async def info_command(args: argparse.Namespace) -> int:
    cfg = load_config()
    session = resolve_session_path(args.session, cfg)
    session_file = Path(session + ".session")

    print(f"config:   {config_path()}")
    print(f"session:  {session_file} ({'есть' if session_file.exists() else 'нет'})")
    print(f"version:  {APP_VERSION}")

    try:
        api_id, api_hash = resolve_credentials(args.api_id, args.api_hash, interactive=False)
    except SystemExit as exc:
        print(f"api:      не настроен ({exc})")
        return 1
    print(f"api_id:   {api_id}")

    if not session_file.exists():
        print("статус:   сессия не создана, выполните `login`")
        return 1

    client = make_client(api_id, api_hash, session, flood_threshold=args.flood_threshold)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("статус:   не авторизован, выполните `login`")
            return 1
        me = await client.get_me()
        username = f"@{me.username}" if getattr(me, "username", None) else ""
        print(f"аккаунт:  {entity_title(me)} {username} (id {me.id})")
        print("статус:   авторизован")
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
