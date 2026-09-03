@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0live-cjj-tpe.ps1"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Live test failed with exit code %RC%.
pause
exit /b %RC%
