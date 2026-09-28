@echo off
rem Yonc UI Launcher
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-yonc.ps1" %*
exit /b %ERRORLEVEL%
