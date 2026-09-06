@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."

if not exist ".venv-provider-poc\Scripts\python.exe" (
  echo [FIRST RUN] Preparing isolated Naver test environment automatically...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-and-unit-test.ps1"
  if errorlevel 1 (
    echo [ERROR] Automatic setup failed.
    pause
    exit /b 2
  )
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ==================================================
echo  NAVER DIRECT API SSE PROBE - CJJ to TPE round trip
echo  2026-09-18 to 2026-09-20 / direct only
echo  No browser - validates current Naver flight API path
echo ==================================================
echo.

".venv-provider-poc\Scripts\python.exe" "scripts\naver_api_sse_probe.py"
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" (
  echo NAVER API SSE probe finished: PASS
) else (
  echo NAVER API SSE probe finished: FAIL ^(exit %RC%^)
)
echo.
pause
exit /b %RC%
