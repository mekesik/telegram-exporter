# Telegram Exporter (MTProto, свой аккаунт)

Экспорт чатов, каналов, групп, «Избранного», папок (разделов) и форумов Telegram
через **ваш собственный аккаунт** по MTProto, а не через бота.

Это важно для чатов с запретом пересылки: бот не видит такой контент, а ваш
авторизованный аккаунт видит его так же, как обычное приложение Telegram.
Скрипт не обходит права доступа — он просто читает то, что уже доступно вашему
аккаунту.

## Быстрый старт

1. Установите Python 3.10 или новее.
2. Скачайте ZIP репозитория с GitHub или клонируйте его.
3. В Windows запустите `run.bat` двойным щелчком. Если зависимости ещё не установлены, сначала выполните в папке проекта:

```powershell
python -m pip install -r requirements.txt
```

Меню `run.bat` предлагает вход по телефону или QR, список чатов, экспорт по ID/ссылке/названию, продолжение прерванной выгрузки, открытие HTML-архива, сброс и настройку бота-уведомлений. Чтобы вернуться к меню после команды, нажмите любую клавишу.

Можно запускать команды напрямую:

```powershell
python -m telegram_exporter login
python -m telegram_exporter list
python -m telegram_exporter export "Название чата"
python -m telegram_exporter export -1001234567890
python -m telegram_exporter export "Название чата" --incremental
```

В Windows вместо `python` также можно использовать `py -3`.

## Возможности

- вход по номеру телефона, коду и паролю 2FA или по QR-коду;
- список чатов, каналов, групп и «Избранного»;
- список папок (разделов) Telegram и экспорт целой папки;
- форумы: автоматическое разбиение на темы (topics) с отдельными страницами;
- медиа: фото, видео, кружки, голосовые, аудио, стикеры, GIF, документы;
- форматы: HTML для чтения, JSONL/JSON для обработки, TXT и CSV;
- инкрементальный экспорт: докачивает только новые сообщения;
- фильтры по датам и лимиту сообщений;
- продолжение после обрыва: частичные данные сохраняются;
- уведомления в Telegram-бота: что скачано и что осталось.

## Установка

Нужен Python 3.10+ (проверено на Python 3.14, Telethon 1.36).

```powershell
cd C:\путь\к\папке\проекта
python -m pip install -r requirements.txt
```

Проверка:

```powershell
python -m telegram_exporter --help
```

## Получение api_id и api_hash

1. Откройте <https://my.telegram.org> и войдите своим номером.
2. Перейдите в **API development tools**.
3. Создайте приложение (название и платформа — любые).
4. Скопируйте `api_id` и `api_hash`.

При первом запуске скрипт спросит их и сохранит в
`C:\Users\<вы>\.telegram_exporter\config.json`.

Можно также задать через переменные окружения:

```powershell
$env:TELEGRAM_API_ID="1234567"
$env:TELEGRAM_API_HASH="0123456789abcdef0123456789abcdef"
```

## Вход в аккаунт

По номеру телефона:

```powershell
python -m telegram_exporter login
```

По QR-коду (удобно, если код не приходит):

```powershell
python -m telegram_exporter login --qr
```

Для QR: Telegram → **Настройки → Устройства → Подключить устройство**, отсканируйте
ссылку/QR из консоли.

Проверить, что сессия жива:

```powershell
python -m telegram_exporter info
```

Файл сессии лежит в `C:\Users\<вы>\.telegram_exporter\sessions\default.session`.
**Он даёт полный доступ к аккаунту. Никому его не передавайте.**

## Основные команды

```powershell
# список всех чатов, каналов и групп
python -m telegram_exporter list

# поиск по названию/username
python -m telegram_exporter list --search "новости"

# только каналы
python -m telegram_exporter list --type channel

# папки (разделы), которые вы создали в Telegram
python -m telegram_exporter folders

# темы конкретного форума
python -m telegram_exporter topics "Название форума"
```

## Экспорт

Один чат по названию, @username, ссылке или id:

```powershell
python -m telegram_exporter export "Название чата"
python -m telegram_exporter export @durov
python -m telegram_exporter export https://t.me/durov
python -m telegram_exporter export -1001234567890
```

Несколько чатов сразу:

```powershell
python -m telegram_exporter export @channel1 @channel2 "Рабочий чат"
```

Целая папка (раздел):

```powershell
python -m telegram_exporter export --folder "Работа"
python -m telegram_exporter export --folder "Архив"
```

Все диалоги:

```powershell
python -m telegram_exporter export --all
```

Только каналы из всех диалогов:

```powershell
python -m telegram_exporter export --all --type channel
```

Период:

```powershell
python -m telegram_exporter export "Название" --since 2024-01-01 --until 2024-12-31
```

Последние 500 сообщений:

```powershell
python -m telegram_exporter export "Название" --limit 500
```

Без медиа (только текст и метаданные):

```powershell
python -m telegram_exporter export "Название" --no-media
```

Только фото и видео:

```powershell
python -m telegram_exporter export "Название" --media-types photo,video
```

Не скачивать файлы больше 500 МБ:

```powershell
python -m telegram_exporter export "Название" --max-media-size 500MB
```

Форум целиком одной страницей, без разбиения на темы:

```powershell
python -m telegram_exporter export "Форум" --no-split-topics
```

Докачать только новое с прошлого запуска:

```powershell
python -m telegram_exporter export --folder "Работа" --incremental
```

Форматы (по умолчанию HTML; JSONL пишется всегда):

```powershell
python -m telegram_exporter export "Название" --format html,json,csv,txt
```

## Уведомления в Telegram-бота

Можно подключить отдельного бота, который будет присылать отчёты: старт экспорта,
сколько сообщений и файлов уже скачано, сколько осталось в текущем чате, сколько
чатов ещё в очереди, итог и ошибки.

Бот — **только канал уведомлений**. Он не получает вашу сессию, не читает чаты и
не может обойти ограничения Telegram. Экспорт по-прежнему выполняется вашим
аккаунтом.

### Настройка

1. Откройте [@BotFather](https://t.me/BotFather), отправьте `/newbot` и скопируйте токен.
2. Откройте созданного бота в Telegram и нажмите **/start** (без этого бот не сможет написать вам первым).
3. Укажите токен и определите `chat_id`:

```powershell
python -m telegram_exporter bot --token "123456789:AAExampleToken"
python -m telegram_exporter bot --detect
```

4. Проверьте связь:

```powershell
python -m telegram_exporter bot --test
```

5. Запускайте экспорт как обычно:

```powershell
python -m telegram_exporter export "Название чата"
```

В `run.bat` это пункт меню **8. Set up bot notifications**.

### Команды бота

```powershell
python -m telegram_exporter bot                    # показать текущие настройки
python -m telegram_exporter bot --token "..."      # сохранить токен
python -m telegram_exporter bot --chat 123456789   # указать chat_id вручную
python -m telegram_exporter bot --detect           # взять chat_id из последнего /start
python -m telegram_exporter bot --test             # тестовое сообщение
python -m telegram_exporter bot --every 120        # отчёт о прогрессе каждые 2 минуты
python -m telegram_exporter bot --clear            # удалить настройки
```

Для группы или канала `chat_id` отрицательный (например, `-1001234567890`).
Добавьте бота в группу и отправьте там сообщение, затем выполните `--detect`.

### Флаги экспорта

```powershell
# разовые настройки без сохранения в config.json
python -m telegram_exporter export "Название" --bot-token "..." --bot-chat 123456789

# писать прогресс реже, раз в 5 минут
python -m telegram_exporter export --all --bot-every 300

# отключить уведомления для этого запуска
python -m telegram_exporter export --all --no-bot
```

Токен и `chat_id` можно хранить в `config.json` (`bot_token`, `bot_chat_id`,
`bot_every`) или в переменных окружения:

```powershell
$env:TELEGRAM_BOT_TOKEN="123456789:AAExampleToken"
$env:TELEGRAM_BOT_CHAT_ID="123456789"
```

Ошибки отправки сообщений не прерывают экспорт: они только выводятся в консоль.
Не публикуйте токен бота в GitHub — `config.json` уже исключён из Git.

## Что получится

```
exports/
  index.html                         # список всех экспортированных чатов
  manifest.json
  Название чата (-1001234567890)/
    chat.json                        # метаданные чата
    state.json                       # состояние для --incremental
    topics.json                      # темы форума (если есть)
    messages.jsonl                   # все сообщения, по одному JSON на строку
    messages.html                    # читаемая страница
    messages.txt
    messages.csv
    messages.json
    media/
      photos/
      videos/
      round/
      voice/
      audio/
      stickers/
      gifs/
      files/
    topics/                          # только для форумов
      0001_General/
        messages.html
        messages.jsonl
        ...
      0010_Название_темы/
        ...
```

Откройте `exports\index.html` в браузере. Страницы полностью локальные,
интернет для просмотра не нужен.

`messages.jsonl` — самый полный формат: текст, HTML-разметка, отправитель,
ответы, пересылки, реакции, просмотры, вложения, служебные сообщения, id темы.
Если нужны вообще все поля Telegram-объекта, добавьте `--raw`.

Если HTML/TXT/CSV были удалены или нужно перегенерировать их после правки
`chat.json`, используйте:

```powershell
python -m telegram_exporter render "exports"
```

## Про запрет пересылки (`noforwards`)

Если в канале/чате включена защита контента, официальные клиенты запрещают
другим пользователям пересылать и сохранять сообщения, а боты получают ошибку.
Ваш собственный аккаунт при этом продолжает видеть сообщения — скрипт использует
именно пользовательскую MTProto-сессию, поэтому может выгрузить текст и вложения,
доступные вашему аккаунту.

Скрипт не получает доступ к тому, чего у вашего аккаунта нет: закрытые чаты, чаты
без вашего участия, удалённые сообщения, истёкшие медиа, секретные (end-to-end)
чаты. Ответственность за использование экспортированных материалов (авторские
права, приватность, правила Telegram) несёте вы.

## Ограничения

- Секретные чаты (E2E) недоступны через MTProto — их нельзя экспортировать.
- Комментарии (обсуждения) под постами каналов не входят в экспорт канала: сохраняется сам канал/чат. Если обсуждение — это отдельная группа, её можно экспортировать отдельно.
- Удалённые сообщения и «истёкшие» медиа не скачиваются.
- Очень большие аккаунты и каналы обрабатываются долго; Telegram может отвечать
  `FloodWait`. По умолчанию скрипт сам ждёт до часа (`--flood-threshold`), после
  чего просит повторить позже.
- Скачивание идёт последовательно, чтобы снизить риск блокировки. Это надёжнее,
  но не мгновенно.
- Приватные чаты без @username находятся по точному названию или id. Если
  название неоднозначно, используйте id из `list`.

## Частые проблемы

**`Не нашёл чат ...` / `Could not find the input entity`**

Выполните `python -m telegram_exporter list`, затем используйте id или @username
из списка. Для приватных чатов это самый надёжный способ.

**`api_id/api_hash неверны`**

Проверьте значения на <https://my.telegram.org>. Конфиг:
`C:\Users\<вы>\.telegram_exporter\config.json`.

**Код не приходит**

Попробуйте `login --qr`. Или запросите код ещё раз; Telegram может прислать его
в приложение, SMS или звонком.

**`FloodWait`**

Подождите указанное время. Можно увеличить `--flood-threshold` (в секундах) или
запускать экспорт частями через `--limit` и `--since/--until`.

**В HTML не отображается видео/стикер**

Проверьте, что файл существует в `media/...` и что формат поддерживается
браузером (`.tgs`-стикеры браузер не показывает — они лежат как файлы).

**Антивирус/Windows блокирует много файлов**

Экспорт создаёт тысячи файлов; добавьте папку `exports` в исключения или
используйте `--no-media`.

## HTML просмотрщик и сброс

Экспорт создаёт локальные HTML страницы: для форума откройте корневую страницу чата и выберите тему. Сверху есть переключатель RU/EN; страница и медиа открываются локально.

Сбросить сообщения и медиа, сохранив карточки чатов, метаданные и дату первого экспорта:

```powershell
python -m telegram_exporter reset exports
```

Команда спросит подтверждение. Для запуска без вопроса добавьте `--yes`. После сброса можно продолжить или выполнить экспорт заново; данные старого экспорта публично не нужны для публикации проекта на GitHub.

## Проверка без Telegram

Офлайн-тесты не требуют аккаунта:

```powershell
python -m unittest discover -s tests -v
```

## Публикация на GitHub

Создайте пустой репозиторий на GitHub (без README, license и .gitignore), затем в папке проекта выполните команды. Замените адрес репозитория на свой:

```powershell
git init
git add .
git status
git commit -m "Initial Telegram exporter"
git branch -M main
git remote add origin https://github.com/ВАШ_ЛОГИН/ИМЯ_РЕПОЗИТОРИЯ.git
git push -u origin main
```

Для следующих изменений:

```powershell
git add README.md run.bat telegram_exporter tests requirements.txt .gitignore
git commit -m "Update exporter"
git push
```

Файл `.gitignore` исключает `exports/`, конфигурацию и файлы авторизации из Git. Перед публикацией проверьте вывод `git status`: в списке не должно быть личных экспортов, `config.json` или `*.session`. Никогда не загружайте их в публичный репозиторий.

## Безопасность

- Не публикуйте `*.session`, `config.json` и токен бота: конфигурация уже
  исключена из Git через `.gitignore`.
- Не запускайте чужие сборки этого скрипта: код, получивший ваш файл сессии,
  получает доступ к аккаунту.
- Для подозрительных случаев завершите сеанс: `python -m telegram_exporter logout`
  (завершает сессию на сервере и удаляет локальный файл) или через
  Telegram → Настройки → Устройства.

## Лицензия и отказ от ответственности

Этот проект распространяется под лицензией **PolyForm Noncommercial 1.0.0** (подробнее в файле `LICENSE`). 

* **Разрешено:** использовать, изучать и изменять код в личных, учебных и некоммерческих целях.
* **Запрещено:** использовать программу для извлечения коммерческой выгоды, перепродажи, создания платных сервисов (SaaS/ботов) или продажи собранных баз данных. Если вам нужна коммерческая лицензия — свяжитесь со мной.

**Важно:** Инструмент предназначен только для ознакомления. Использование скрапинга может нарушать правила использования Telegram. Автор не несет ответственности за любые ограничения или блокировки ваших аккаунтов.
