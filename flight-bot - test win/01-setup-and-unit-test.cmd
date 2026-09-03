@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-and-unit-test.ps1"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Setup/test failed with exit code %RC%.
pause
exit /b %RC%
