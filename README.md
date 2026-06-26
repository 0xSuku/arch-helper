# Arch Helper

Local Windows helper for Archero 2: build **routine chains** (arena → farm → dungeons…), run them from a **web panel** or the CLI, and recover automatically if a step fails.

Works with **MuMu Player 12** or **LDPlayer 9**. Emulator must be **portrait 900×1600**.

---

## Quick start (ZIP — recommended)

For most users, use the release from [GitHub Releases](https://github.com/0xSuku/arch-helper/releases):

1. Unzip the archive into a folder (e.g. `C:\ArchHelper`)
2. Run **`Install.cmd`** once (creates `.venv`, installs dependencies)
3. Open **MuMu** (or LDPlayer), launch **Archero 2**, and stay on the **campaign lobby**
4. Run **`Start-Panel.cmd`** — browser opens at `http://127.0.0.1:8765`

**First time in the panel**

1. Check status pills: **Emulator ON**, **ADB OK**
2. Open **Guide** (collapsible section) → **Basic usage** for the full walkthrough
3. In **Your routine**: pick actions from **Library**, order them in **Chain**, click **▶ Run chain**
4. Or choose a **Saved preset** (e.g. `5-arena-farm`) and run

More detail: **`INSTALLATION.md`** (in the ZIP) and **`docs/GUIDE.md`** (same text as the in-panel Guide).

Other launchers in the ZIP:

| File | Purpose |
|------|---------|
| `Start-Panel.cmd` | Web panel (main UI) |
| `Run-Bot.cmd` | Run a preset from the console |
| `Install.cmd` | One-time setup |

---

## Panel overview

| Section | What it does |
|---------|----------------|
| **Your routine** | Library → Chain → Run; save/load presets |
| **Guide** | Basic usage, then Advanced (CLI, skills, calibration…) |
| **Emulator & stop** | Launch game, reconnect ADB, STOP file |
| **Solo claims** | Run one daily claim outside a chain |
| **Skill scores** | Edit scores; group duplicate skill images; delete bad captures |
| **Log & daily checks** | Live log and daily claim status |

**Stop the bot:** **STOP** in the panel, or create a `STOP` file in the bot folder.

**After a failure:** with auto-recovery on, progress is saved in `data/run-state.json` — use **↻ Resume pending** or `python -m bot.cli run --resume`.

---

## Presets & routine chains

Bundled presets (also in `config/presets.json`, copied to `data/presets.json` on first run):

| Preset | What it does |
|--------|----------------|
| `5-arena-farm` | 5 arena fights, then farm forever |
| `arena-farm` | Default arena + farm |
| `shackled-2` | 2 Shackled Jungle runs |
| `daily-main` | Main daily loop |
| `arena-shackled-farm` | Arena + Shackled + farm forever |

**CLI**

```powershell
python -m bot.cli run 5-arena-farm
python -m bot.cli run arena:5 farm:forever shackled:2
python -m bot.cli run --resume
python -m bot.cli presets list
python -m bot.cli presets save my-bot --steps arena:3 farm:forever
```

User data (portable, safe to back up): `data/presets.json`, `data/run-state.json`. Override folder with env `ARCHERO_DATA_DIR`.

---

## Developers

**Requirements:** Windows 10/11, Python 3.12+, Git, MuMu 12 or LDPlayer 9, Google Play Services + Archero 2 on the emulator.

```powershell
git clone git@github.com:0xSuku/arch-helper.git
cd arch-helper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # edit emulator path if needed
```

**Run the panel**

```powershell
python -m bot.cli panel
```

Open `http://127.0.0.1:8765`.

**Smoke checks**

```powershell
python -m bot.cli emulator status
python -m bot.cli calibrate --shot check.png --identify
python -m bot.cli farm --level 50 --forever
```

**Build release ZIP**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-release.ps1
```

Output: `dist/arch-helper-vX.Y.Z-windows.zip`.

**Tests**

```powershell
python -m unittest discover -s tests -v
```

---

## Configuration

| Path | Purpose |
|------|---------|
| `.env` | Emulator path, ADB port, game package |
| `config/coords.json` | Tap regions and UI anchors |
| `config/daily-claims.json` | Daily claim definitions |
| `config/skills.json` | Skill scores and categories |
| `config/presets.json` | Default preset seed |
| `templates/` | Screen matching images |
| `logs/bot.log` | Runtime log |

Default MuMu `.env` values:

```env
EMULATOR=mumu
EMULATOR_DIR=D:\Program Files\Netease\MuMuPlayer\nx_main
EMULATOR_INDEX=0
ADB_HOST=127.0.0.1
ADB_PORT=16384
GAME_PACKAGE=com.xq.archeroii
```

---

## Notes

- Keep emulator resolution at **900×1600 portrait**
- Install Google Play Services and Archero 2 on the **same** Play profile
- Only one `farm`/`play`/pipeline job at a time
- Optional Tauri desktop app exists in a separate worktree; the ZIP + panel is the recommended path for most users
