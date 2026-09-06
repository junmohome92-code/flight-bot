@echo off
setlocal
chcp 65001 >nul 2>nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0notification-test-menu.ps1"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Notification test menu exited with code %RC%.
pause
exit /b %RC%
