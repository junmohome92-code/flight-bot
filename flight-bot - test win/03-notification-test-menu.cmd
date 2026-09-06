@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0notification-test-menu.ps1"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Notification test menu exited with code %RC%.
pause
exit /b %RC%
