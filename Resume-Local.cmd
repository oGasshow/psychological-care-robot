@echo off
setlocal
set "PATH=%~dp0runtime\local-tools\node-v22.14.0-win-x64;%PATH%"
call "%~dp0Resume-Project.cmd" -NoBrowser
exit /b %errorlevel%
