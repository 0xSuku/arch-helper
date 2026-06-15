# Arch Helper

Local Windows helper for running repeatable Archero 2 emulator routines from the command line or a small local panel.

## Requirements

- Windows 10/11
- Python 3.12+
- Git
- MuMu Player 12, or LDPlayer 9
- Google Play Services installed and signed in
- Archero 2 installed in the emulator
- Emulator resolution set to vertical `900 x 1600`

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

## Setup

Clone the repo:

```powershell
git clone git@github.com:0xSuku/arch-helper.git
cd arch-helper
```

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy the example environment file if your emulator path or ADB port differs:

```powershell
Copy-Item .env.example .env
notepad .env
```

Default MuMu values:

```env
EMULATOR=mumu
EMULATOR_DIR=D:\Program Files\Netease\MuMuPlayer\nx_main
EMULATOR_INDEX=0
ADB_HOST=127.0.0.1
ADB_PORT=16384
GAME_PACKAGE=com.xq.archeroii
```

Install and sign in to Google Play Services before installing Archero 2. Then install/open Archero 2 from that same Play profile so the saved profile loads correctly.

## Quick Check

Open the emulator, open the game, and leave it on the main lobby.

Check emulator/ADB:

```powershell
python -m bot.cli emulator status
python -m bot.cli emulator reconnect
```

Check screen detection:

```powershell
python -m bot.cli calibrate --shot check.png --identify
```

The screenshot is saved under `screenshots/`.

## Run Level 50 Continuously

From the project folder:

```powershell
python -m bot.cli farm --level 50 --forever
```

Optional wait interval:

```powershell
python -m bot.cli farm --level 50 --forever --energy-wait 60
```

Stop with `Ctrl+C`, or create a `STOP` file in the repo root.

```powershell
New-Item STOP -ItemType File
```

Remove it before starting again:

```powershell
Remove-Item STOP
```

Only one `farm`/`play` run can be active at a time.

## Local Panel

Start the local panel:

```powershell
python -m bot.cli panel
```

Open:

```text
http://127.0.0.1:8765
```

The panel exposes the common actions, status, logs, and skill priority editing.

## Useful Commands

```powershell
python -m bot.cli daily --list
python -m bot.cli daily --status
python -m bot.cli skills list
python -m bot.cli calibrate --identify
python -m bot.cli emulator reboot
```

## Notes

- Keep the emulator resolution consistent.
- Coordinates live in `config/coords.json`.
- Logs are written to `logs/bot.log`.
- Failure screenshots are written to `screenshots/dumps/`.
- Templates live in `templates/`.
- If the game UI changes, capture a screenshot and update the matching coordinate/template.

## Desktop App

A Windows desktop UI can be built with the Tauri app in the desktop worktree. For releases, the usual flow is:

1. Build the Tauri app on Windows.
2. Upload the installer to GitHub Releases.
3. Keep Python/runtime requirements documented, or bundle them in a later portable build.

Bundling only the UI is simple. Bundling Python, OpenCV, ADB, templates, and the runtime into a single installer is doable, but should be treated as a separate packaging step.
