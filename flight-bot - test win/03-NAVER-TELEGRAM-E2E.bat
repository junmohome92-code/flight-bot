@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."

if not exist ".venv-provider-poc\Scripts\python.exe" (
  echo [FIRST RUN] Preparing isolated Naver SSE test environment automatically...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-and-unit-test.ps1"
  if errorlevel 1 (
    echo [ERROR] Automatic setup failed.
    pause
    exit /b 2
  )
)

if not exist "flight-bot - test win\telegram-test.env" (
  copy /Y "flight-bot - test win\telegram-test.env.example" "flight-bot - test win\telegram-test.env" >nul
  echo.
  echo [SETUP NEEDED] telegram-test.env was created.
  echo Fill these two values, save, then run this BAT again:
  echo   TELEGRAM_BOT_TOKEN=...
  echo   TELEGRAM_ALLOWED_CHAT_IDS=...
  echo.
  start "" notepad.exe "flight-bot - test win\telegram-test.env"
  pause
  exit /b 3
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ==================================================
echo  NAVER SSE -^> TELEGRAM E2E TEST
echo  CJJ to TPE round trip / 2026-09-18 to 2026-09-20
echo  Direct only / no browser / TOP 5 fare combinations
echo ==================================================
echo.

".venv-provider-poc\Scripts\python.exe" "scripts\naver_telegram_e2e.py"
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" (
  echo NAVER SSE -^> TELEGRAM E2E finished: PASS
) else (
  echo NAVER SSE -^> TELEGRAM E2E finished: FAIL ^(exit %RC%^)
  echo Check artifacts\naver-telegram-e2e\
)
echo.
pause
exit /b %RC%
