@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

:menu
cls
echo ==========================================
echo        Tgk Alg0rithmX - Telegram Exporter
echo ==========================================
echo.
echo 1. Login with phone/code
echo 2. Login with QR
echo 3. List chats
echo 4. Export a chat by ID, username or name
echo 5. Continue interrupted export
echo 6. Open HTML archive
echo 7. Reset exported messages/media
echo 8. Set up bot notifications
echo 9. Show command help
echo 0. Exit
echo.
set "choice="
set /p "choice=Select: "
if not defined choice goto end

if "%choice%"=="1" goto login
if "%choice%"=="2" goto qr
if "%choice%"=="3" goto list
if "%choice%"=="4" goto export
if "%choice%"=="5" goto resume
if "%choice%"=="6" goto open
if "%choice%"=="7" goto reset
if "%choice%"=="8" goto bot
if "%choice%"=="9" goto help
if "%choice%"=="0" goto end
echo Invalid selection.
pause
goto menu

:login
"%PY%" -m telegram_exporter login
pause
goto menu

:qr
"%PY%" -m telegram_exporter login --qr
pause
goto menu

:list
"%PY%" -m telegram_exporter list
pause
goto menu

:export
echo Example IDs: -1001234567890, @channelname, or "Group name"
set "chat="
set /p "chat=Chat: "
if not defined chat goto menu
"%PY%" -m telegram_exporter export "%chat%"
pause
goto menu

:resume
echo Enter the same chat/folder selection used for the previous export.
set "chat="
set /p "chat=Chat, or leave blank to export all: "
if not defined chat (
  "%PY%" -m telegram_exporter export --all --incremental
) else (
  "%PY%" -m telegram_exporter export "%chat%" --incremental
)
pause
goto menu

:open
if exist "exports\index.html" (
  start "" "exports\index.html"
) else (
  echo No archive yet. Export a chat first.
  pause
)
goto menu

:reset
echo This removes exported messages and media but keeps chat metadata and dates.
set "confirm="
set /p "confirm=Type YES to confirm reset: "
if /i not "%confirm%"=="YES" goto menu
"%PY%" -m telegram_exporter reset exports --yes
pause
goto menu

:bot
echo The bot only reports progress: it cannot read your chats or your session.
echo Create a bot with @BotFather and copy its token.
set "btoken="
set /p "btoken=Bot token (leave blank to keep current): "
if defined btoken (
  "%PY%" -m telegram_exporter bot --token "%btoken%"
) else (
  "%PY%" -m telegram_exporter bot
)
echo.
echo Open the bot in Telegram and press /start, then continue.
pause
"%PY%" -m telegram_exporter bot --detect
pause
"%PY%" -m telegram_exporter bot --test
pause
goto menu

:help
"%PY%" -m telegram_exporter --help
pause
goto menu

:end
endlocal
