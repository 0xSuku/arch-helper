# Arch Helper — Guía de instalación (Windows)

Bot local para Archero 2. **No hace trampas online**: solo automatiza clics en tu emulador, como si los hicieras vos.

## Qué necesitás antes de empezar

1. **Windows 10 u 11**
2. **Python 3.12 o más nuevo**  
   - Descargá desde [python.org](https://www.python.org/downloads/)  
   - En el instalador, marcá **“Add python.exe to PATH”** (muy importante)
3. **MuMu Player 12** (recomendado) o LDPlayer 9
4. **Google Play Services** instalado y con sesión iniciada en el emulador
5. **Archero 2** instalado en el mismo perfil de Google Play
6. Resolución del emulador en **vertical 900 × 1600**

## Instalación rápida (3 clics)

1. Descomprimí el ZIP del release en una carpeta, por ejemplo `C:\ArchHelper`
2. Doble clic en **`Instalar.cmd`**  
   - Crea el entorno Python e instala dependencias (solo la primera vez)
   - Si falta Python, el script te lo indica
3. Si es la primera vez, editá **`.env`** si tu MuMu no está en la ruta por defecto  
   (copiá desde `.env.example` si no existe `.env`)

## Uso diario — Panel de escritorio

1. Abrí **MuMu** y entrá al **lobby principal** de Archero 2 (mapa de campaña)
2. Doble clic en **`Iniciar-Panel.cmd`**
3. Se abre el navegador en `http://127.0.0.1:8765`
4. En el panel:
   - **Abrir emulador** / **Reconectar ADB** si hace falta
   - **Farm energía** para jugar nivel 50
   - Botones **Daily** para claims (Arena, Shackled, etc.)
   - **STOP** para frenar antes de la próxima acción

Para cerrar: cerrá la ventana negra del panel o apretá `Ctrl+C` ahí.

## Configuración del emulador (`.env`)

Abrí el archivo `.env` con Bloc de notas. Lo más usual en MuMu:

```env
EMULATOR=mumu
EMULATOR_DIR=D:\Program Files\Netease\MuMuPlayer\nx_main
EMULATOR_INDEX=0
ADB_HOST=127.0.0.1
ADB_PORT=16384
GAME_PACKAGE=com.xq.archeroii
```

Si usás LDPlayer, descomentá las líneas de LDPlayer en `.env.example`.

## Arena (ejemplo)

Desde el panel o la consola:

```text
Arena con máximo 4.5M de poder, 2 peleas
```

Equivalente en consola (opcional):

```powershell
python -m bot.cli daily arena --force --arena-fights 2 --arena-max-power 4.5
```

## Problemas frecuentes

| Problema | Qué hacer |
|----------|-----------|
| “Python no encontrado” | Reinstalá Python marcando **Add to PATH** |
| ADB desconectado | Panel → **Reconectar ADB** (emulador abierto) |
| Pantalla `unknown` | Dejá el juego en el lobby y reconectá |
| El bot toca mal | No cambies la resolución; debe ser 900×1600 vertical |
| Quiero frenar ya | Botón **STOP** en el panel o crear archivo `STOP` en la carpeta del bot |

## Soporte técnico (opcional)

Consola en la carpeta del bot (con `.venv` activado):

```powershell
python -m bot.cli emulator status
python -m bot.cli calibrate --identify
python -m bot.cli daily --list
```

Logs: carpeta `logs\bot.log`
