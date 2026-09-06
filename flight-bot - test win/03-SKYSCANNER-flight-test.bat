@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."

if not exist ".venv-win\Scripts\python.exe" (
  echo [ERROR] Run 01-setup-and-unit-test.cmd first.
  pause
  exit /b 2
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ==================================================
echo  SKYSCANNER POC - CJJ to TPE round trip
echo  2026-09-18 to 2026-09-20 / direct only
echo  Visible Microsoft Edge / no booking navigation
echo ==================================================
echo.

".venv-win\Scripts\python.exe" "scripts\skyscanner_flight_probe.py"
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" (
  echo SKYSCANNER POC finished: PASS
) else (
  echo SKYSCANNER POC finished: FAIL ^(exit %RC%^) 
  echo Check artifacts\skyscanner-flight-poc\page.png and result.json
)
echo.
pause
exit /b %RC%
