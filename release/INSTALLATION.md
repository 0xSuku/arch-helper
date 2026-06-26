# Arch Helper — Installation guide (Windows)

Local bot for Archero 2. **Not online cheating**: it only automates taps on your emulator, like you would manually.

## Before you start

1. **Windows 10 or 11**
2. **Python 3.12 or newer**  
   - Download from [python.org](https://www.python.org/downloads/)  
   - In the installer, check **“Add python.exe to PATH”** (important)
3. **MuMu Player 12** (recommended) or LDPlayer 9
4. **Google Play Services** installed and signed in on the emulator
5. **Archero 2** installed on the same Google Play profile
6. Emulator resolution set to **portrait 900 × 1600**

## Quick install (3 steps)

1. Unzip the release into a folder, e.g. `C:\ArchHelper`
2. Double-click **`Install.cmd`**  
   - Creates the Python environment and installs dependencies (first time only)
   - If Python is missing, the script tells you
3. On first run, edit **`.env`** if your MuMu path differs  
   (copy from `.env.example` if `.env` does not exist)

## Daily use — desktop panel

1. Open **MuMu** and reach the **main Archero 2 lobby** (campaign map)
2. Double-click **`Start-Panel.cmd`**
3. Browser opens at `http://127.0.0.1:8765`
4. In the panel:
   - Expand **Guide** when needed (**Basic usage** → **Advanced**)
   - **Launch emulator** / **Reconnect ADB** if needed
   - Build your **routine chain** and **Run chain**
   - **STOP** to halt before the next action

To close: close the panel console window or press `Ctrl+C` there.

## Custom bot (presets)

Chain actions and save your own bots in **`data/presets.json`**.

Double-click **`Run-Bot.cmd`** or from a console:

```powershell
python -m bot.cli run 5-arena-farm
python -m bot.cli run arena:5 farm:forever shackled:2
python -m bot.cli run --resume
python -m bot.cli presets list
python -m bot.cli presets save my-bot --steps arena:3 farm:forever
```

If a step fails, the bot saves state in **`data/run-state.json`**, restarts the emulator/game, and you can resume with `--resume`.

Default presets: `5-arena-farm`, `arena-farm`, `shackled-2`, `daily-main`, `arena-shackled-farm`.

## Emulator configuration (`.env`)

Open `.env` in Notepad. Typical MuMu values:

```env
EMULATOR=mumu
EMULATOR_DIR=D:\Program Files\Netease\MuMuPlayer\nx_main
EMULATOR_INDEX=0
ADB_HOST=127.0.0.1
ADB_PORT=16384
GAME_PACKAGE=com.xq.archeroii
```

For LDPlayer, uncomment the LDPlayer lines in `.env.example`.

## Arena (example)

From the panel or console:

```text
Arena with max 4.5M power, 2 fights
```

CLI equivalent:

```powershell
python -m bot.cli daily arena --force --arena-fights 2 --arena-max-power 4.5
```

## Troubleshooting

| Problem | What to do |
|----------|-----------|
| “Python not found” | Reinstall Python with **Add to PATH** checked |
| ADB disconnected | Panel → **Reconnect ADB** (emulator running) |
| Screen `unknown` | Leave the game on the lobby and reconnect |
| Wrong taps | Do not change resolution; use 900×1600 portrait |
| Stop immediately | **STOP** in the panel or create a `STOP` file in the bot folder |

## Technical support (optional)

Console in the bot folder (with `.venv` active):

```powershell
python -m bot.cli emulator status
python -m bot.cli calibrate --identify
python -m bot.cli daily --list
```

Logs: `logs\bot.log`

## Full usage guide

- **In the panel**: open the **Guide** section (Basic usage → Advanced tabs).
- **In the ZIP / repo**: `docs/GUIDE.md` (same content as the panel).
