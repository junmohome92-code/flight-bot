@echo off
setlocal
cd /d "%~dp0.."
set "PY=%CD%\.venv-win\Scripts\python.exe"
if not exist "%PY%" (
  echo Windows test environment was not found.
  echo Run: flight-bot - test win\01-setup-and-unit-test.cmd
  echo.
  pause
  exit /b 2
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo.
echo Running Google Flights with installed Microsoft Edge...
echo This does NOT enter Booking, OTA, or checkout pages.
echo.
"%PY%" "scripts\google_msedge_probe.py"
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo Google msedge test: SUCCESS
) else (
  echo Google msedge test: FAILED ^(code %RC%^)
  echo Check artifacts\google-msedge-win
)
echo.
pause
exit /b %RC%
