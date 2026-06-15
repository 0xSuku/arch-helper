# Arch Helper

Herramienta local para asistir tareas repetitivas en Archero 2 desde un emulador Android en Windows.

La idea es que puedas abrir el emulador, dejar la pantalla en el lobby principal y ejecutar comandos simples desde una terminal. El proyecto usa ADB para leer la pantalla y enviar taps/swipes, con reglas de seguridad para no tocar compras con dinero real.

## Que necesitás instalar

### 1. Python

Instalá Python 3.12 o superior desde:

https://www.python.org/downloads/windows/

Durante la instalación marcá:

- `Add python.exe to PATH`
- `pip`

Para confirmar que quedó bien:

```powershell
python --version
pip --version
```

### 2. Git

Instalá Git para Windows:

https://git-scm.com/download/win

Confirmá:

```powershell
git --version
```

### 3. Emulador Android

La configuración por defecto está pensada para **MuMu Player 12**. También se puede usar LDPlayer 9.

Recomendado para empezar:

- MuMu Player 12 instalado.
- Archero 2 instalado dentro del emulador.
- Resolución del emulador: **900 x 1600 vertical**.
- El juego abierto en el lobby principal.

El archivo `.env.example` trae valores base para MuMu:

```env
EMULATOR=mumu
EMULATOR_DIR=D:\Program Files\Netease\MuMuPlayer\nx_main
EMULATOR_INDEX=0
ADB_HOST=127.0.0.1
ADB_PORT=16384
GAME_PACKAGE=com.xq.archeroii
SCREEN_WIDTH=1600
SCREEN_HEIGHT=900
```

Si tu instalación está en otra carpeta, copiá `.env.example` a `.env` y editá `EMULATOR_DIR`.

```powershell
Copy-Item .env.example .env
notepad .env
```

## Instalación del proyecto

Cloná el repositorio:

```powershell
git clone git@github.com:0xSuku/arch-helper.git
cd arch-helper
```

Creá un entorno virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Si PowerShell bloquea la activación, usá:

```powershell
powershell -ExecutionPolicy Bypass -NoProfile
.\.venv\Scripts\Activate.ps1
```

Instalá dependencias:

```powershell
pip install -r requirements.txt
```

## Primer chequeo

Con el emulador abierto y el juego en el lobby, probá:

```powershell
python -m bot.cli emulator status
```

Si ADB no conecta, probá:

```powershell
python -m bot.cli emulator reconnect
```

Para confirmar que puede ver la pantalla:

```powershell
python -m bot.cli calibrate --shot prueba.png --identify
```

Eso guarda una captura en `screenshots/prueba.png` y muestra qué pantalla detectó.

## Correr nivel 50

### Una cantidad fija de partidas

Para correr 5 partidas del nivel 50:

```powershell
python -m bot.cli play --level 50 --games 5
```

### Consumir energía disponible

Para correr nivel 50 hasta quedarse sin energía o llegar al límite de seguridad:

```powershell
python -m bot.cli farm --level 50
```

Por defecto tiene `--max-games 40`, para evitar loops accidentales.

Podés cambiarlo:

```powershell
python -m bot.cli farm --level 50 --max-games 10
```

### Modo continuo

Para que espere energía y vuelva a intentar:

```powershell
python -m bot.cli farm --level 50 --forever
```

Cuando aparece un popup para comprar energía, la herramienta lo cierra sin comprar, espera y reintenta. El tiempo default es 60 minutos.

Para cambiar la espera:

```powershell
python -m bot.cli farm --level 50 --forever --energy-wait 30
```

### Movimiento durante partida

Por defecto intenta mantenerse quieto y resolver selección de skills. Si querés activar esquive continuo:

```powershell
python -m bot.cli farm --level 50 --dodge
```

## Cortar una ejecución

La forma más simple:

```powershell
Ctrl+C
```

También podés crear un archivo llamado `STOP` en la raíz del proyecto. La herramienta lo revisa antes de cada acción importante y se detiene.

Para crearlo desde PowerShell:

```powershell
New-Item STOP -ItemType File
```

Para limpiarlo:

```powershell
Remove-Item STOP
```

Importante: solo puede correr un `play` o `farm` a la vez. Si ves:

```text
Ya hay un farm/play corriendo; no inicio otro
```

significa que todavía hay una ejecución activa. Cerrá esa terminal o matá el proceso Python correspondiente.

## Tareas diarias

Ver lista disponible:

```powershell
python -m bot.cli daily --list
```

Correr el grupo principal:

```powershell
python -m bot.cli daily
```

Correr una tarea puntual:

```powershell
python -m bot.cli daily guild
python -m bot.cli daily shop
python -m bot.cli daily hunt
```

Correr varias:

```powershell
python -m bot.cli daily guild friends shop
```

Forzar una tarea aunque ya figure verificada:

```powershell
python -m bot.cli daily shop --force
```

Ver estado de checks:

```powershell
python -m bot.cli daily --status
```

Resetear checks:

```powershell
python -m bot.cli daily --reset-checks all
```

## Panel local

Si preferís botones en navegador:

```powershell
python -m bot.cli panel
```

Después abrí:

```text
http://127.0.0.1:8765
```

Desde ahí podés lanzar tareas, ver logs y editar prioridades de skills.

## Skills y prioridades

La selección de skills usa templates y puntajes configurables. Mayor score significa mayor prioridad.

Listar:

```powershell
python -m bot.cli skills list
```

Setear prioridad:

```powershell
python -m bot.cli skills set dano/bolt 90
```

Subir o bajar un score:

```powershell
python -m bot.cli skills bump dano/bolt 5
python -m bot.cli skills bump dano/bolt -5
```

Escanear la pantalla actual de selección:

```powershell
python -m bot.cli skills scan
```

Durante `play` y `farm`, las cartas no identificadas se guardan en el catálogo para etiquetarlas después desde el panel.

## Calibración rápida

Capturar pantalla:

```powershell
python -m bot.cli calibrate --shot pantalla.png
```

Identificar pantalla actual:

```powershell
python -m bot.cli calibrate --identify
```

Enviar tap de prueba:

```powershell
python -m bot.cli calibrate --tap 450,1523
```

Recortar un template:

```powershell
python -m bot.cli calibrate --crop 200,280,500,90 --out templates/anchors/challenge_ended.png
```

Leer el piso actual del mapa campaña:

```powershell
python -m bot.cli calibrate --read-floor
```

Las coordenadas están en `config/coords.json` y usan el espacio de captura vertical `900x1600`.

## Problemas comunes

### ADB no conecta

Probá:

```powershell
python -m bot.cli emulator reconnect
```

Si sigue fallando:

- Confirmá que el emulador esté abierto.
- Revisá `EMULATOR_DIR` en `.env`.
- Revisá `ADB_PORT`.
- Probá reiniciar el emulador.

### La pantalla detectada no coincide

Sacá una captura:

```powershell
python -m bot.cli calibrate --shot debug.png --identify
```

Abrí `screenshots/debug.png` y compará con la pantalla real. Si cambió la resolución o escala, hay que recalibrar coordenadas/templates.

### Se quedó una ejecución bloqueando otra

Listá procesos Python:

```powershell
wmic process where "name like '%python%'" get ProcessId,CommandLine
```

Luego cerrá el PID correcto:

```powershell
Stop-Process -Id 1234
```

### Loading infinito o emulador congelado

Estado:

```powershell
python -m bot.cli emulator status
```

Reiniciar emulador y esperar lobby:

```powershell
python -m bot.cli emulator reboot
```

Algunas tareas aceptan recovery automático:

```powershell
python -m bot.cli daily guild --recover-emulator
```

## Carpetas importantes

```text
bot/                 Código Python principal
config/              Coordenadas, checks y configuración de skills
templates/           Anchors, botones y templates de skills
screenshots/         Capturas locales y dumps de errores
logs/                Logs de ejecución
tests/               Tests offline
scripts/             Utilidades auxiliares
```

## Recomendaciones

- Usá siempre la misma resolución del emulador.
- Antes de una sesión larga, corré `calibrate --identify`.
- No lances dos `farm/play` al mismo tiempo.
- Revisá `logs/bot.log` cuando algo no cierre bien.
- Si una pantalla cambió por update del juego, guardá screenshot y agregá/regenerá template.
