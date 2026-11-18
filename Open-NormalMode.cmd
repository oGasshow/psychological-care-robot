@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Open-ProjectMode.ps1" -Mode Normal %*
set "launcher_result=%errorlevel%"
if "%~1"=="" pause
exit /b %launcher_result%
