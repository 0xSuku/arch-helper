@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title Arch Helper - Instalacion

echo.
echo  Arch Helper - Instalacion
echo  ========================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta en el PATH.
    echo Instala Python 3.12+ desde https://www.python.org/downloads/
    echo Marca "Add python.exe to PATH" en el instalador.
    pause
    exit /b 1
)

python --version
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear .venv
        pause
        exit /b 1
    )
)

echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install fallo
    pause
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo Creado .env desde .env.example - revisa la ruta de MuMu si hace falta.
    )
)

echo.
echo [OK] Instalacion completa.
echo.
echo Siguiente paso: abri MuMu + Archero 2 en el lobby y ejecuta:
echo   release\Iniciar-Panel.cmd
echo.
pause
