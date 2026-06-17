@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title Arch Helper - Panel

if not exist ".venv\Scripts\python.exe" (
    echo Falta instalar. Ejecuta primero: release\Instalar.cmd
    pause
    exit /b 1
)

if exist "STOP" del /F /Q "STOP" >nul 2>&1

echo Abriendo panel en http://127.0.0.1:8765
echo Cerra esta ventana o Ctrl+C para detener el panel.
echo.

start "" "http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m bot.cli panel --port 8765
