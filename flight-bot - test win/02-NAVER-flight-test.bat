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
echo  NAVER FLIGHTS POC - CJJ to TPE round trip
echo  2026-09-18 to 2026-09-20 / direct only
echo  Visible Microsoft Edge / results page only
echo ==================================================
echo.

".venv-provider-poc\Scripts\python.exe" "scripts\naver_flight_probe.py"
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" (
  echo NAVER POC finished: PASS
) else (
  echo NAVER POC finished: FAIL ^(exit %RC%^)
  echo Check artifacts\naver-flight-poc\page.png
  echo       artifacts\naver-flight-poc\page.txt
  echo       artifacts\naver-flight-poc\page.html
  echo       artifacts\naver-flight-poc\diagnostics.json
  echo       artifacts\naver-flight-poc\result.json
)
echo.
pause
exit /b %RC%
