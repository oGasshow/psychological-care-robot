@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-Project.ps1" %*
set "launcher_result=%errorlevel%"
pause
exit /b %launcher_result%
