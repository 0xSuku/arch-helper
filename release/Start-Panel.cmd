@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title Arch Helper - Panel

if not exist ".venv\Scripts\python.exe" (
    echo Run install first: release\Install.cmd
    pause
    exit /b 1
)

if exist "STOP" del /F /Q "STOP" >nul 2>&1

echo Opening panel at http://127.0.0.1:8765
echo Close this window or Ctrl+C to stop the panel.
echo.

start "" "http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m bot.cli panel --port 8765
