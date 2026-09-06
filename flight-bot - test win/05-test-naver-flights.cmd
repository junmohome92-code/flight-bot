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
echo Running Naver Flights visible viability test with Microsoft Edge...
echo Route: CJJ - TPE - CJJ / 2026-09-18 to 2026-09-20 / direct only
echo This does NOT click Booking, fare detail, OTA, or checkout pages.
echo.
"%PY%" "scripts\naver_flights_probe.py"
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo Naver Flights test: SUCCESS
) else (
  echo Naver Flights test: FAILED ^(code %RC%^)
  echo Check artifacts\naver-flights-win
)
echo.
pause
exit /b %RC%
