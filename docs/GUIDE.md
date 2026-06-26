# Arch Helper — Usage guide

Local automation for Archero 2 on MuMu / LDPlayer. Portrait **900×1600** only.

---

## Basic usage

### What you need running

1. Emulator open (MuMu 12 recommended).
2. Archero 2 on the **campaign lobby** (map screen).
3. Panel status pills green: **Emulator ON**, **ADB OK**, screen shows `lobby` (or similar).

If ADB is red: **Emulator & stop** → **Reconnect ADB**.

### Daily workflow (panel)

1. Start the panel: `Start-Panel.cmd` or `python -m bot.cli panel`.
2. In **Your routine**, pick actions from the **Library** (left) with **+ Add**.
3. Order steps in the **Chain** (center). Uncheck a step to skip it without deleting.
4. Choose a **Saved preset** or build your own chain.
5. Click **▶ Run chain**.

Example chain: **Arena** (5 fights) → **Farm forever**.

### Presets (quick start)

| Preset | What it does |
|--------|----------------|
| `5-arena-farm` | 5 arena fights, then farm until energy runs out (forever mode) |
| `arena-farm` | Default arena (2 fights) + farm |
| `shackled-2` | 2 Shackled Jungle attempts |
| `daily-main` | Main daily loop (no friends) |
| `arena-shackled-farm` | Arena + Shackled + farm forever |

Load one from **Saved preset**, tweak the chain if needed, then **Run chain**.

### Stop the bot

- **STOP** button (creates a `STOP` file; bot halts before the next action).
- **Clear STOP** before starting again.
- Closing the panel window also stops the server.

### When something fails

With **Auto recovery** enabled (default):

1. The bot saves progress in `data/run-state.json`.
2. It restarts the emulator and reopens the game.
3. Click **↻ Resume pending** or run `python -m bot.cli run --resume`.

To discard saved state: **Discard saved state** in the panel or `python -m bot.cli run --clear-state`.

### First-time install (ZIP release)

1. Unzip the release folder.
2. Run **`Install.cmd`** once.
3. Edit **`.env`** if MuMu is not in the default path.
4. Open game on lobby → **`Start-Panel.cmd`**.

See **`INSTALLATION.md`** for full install and troubleshooting.

---

## Advanced usage

### Chain actions (library)

| Category | Actions | Main options |
|----------|---------|----------------|
| Farm & play | Farm energy, Farm forever, Play N games | Level, games, energy wait (min) |
| Dungeons | Shackled, Abyssal, Gold Cave | Attempts (`runs`) |
| Arena | Arena, Peak Arena | Fights, max power (M) |
| Daily | Main daily loop, Rune Ruins | Force, keys |

Toggle steps off in the chain to run a subset without rebuilding.

### Save your own preset

1. Build the chain in the panel.
2. Under **Save as preset**, enter an ID (`my-routine`) and display name.
3. **Save preset** → stored in `data/presets.json`.

CLI:

```powershell
python -m bot.cli presets save my-routine --name "My routine" --steps arena:5 farm:forever
python -m bot.cli presets list
python -m bot.cli presets show my-routine
```

### CLI chains (no panel)

```powershell
python -m bot.cli run 5-arena-farm
python -m bot.cli run arena:5 farm:forever shackled:2
python -m bot.cli run --list
python -m bot.cli run --status
python -m bot.cli run --resume
```

Inline syntax: `action:value` — e.g. `arena:5`, `shackled:2`, `farm:forever`, `play:10`.

### Solo daily claims

Panel → **Solo claims** (single claim, not a chain). Useful for testing one feature.

CLI:

```powershell
python -m bot.cli daily arena --force --arena-fights 2 --arena-max-power 4.5
python -m bot.cli daily shackled --force
python -m bot.cli daily --list
python -m bot.cli daily --status
```

**Force daily claims** checkbox ignores “already done today” checks.

### Farm & play (standalone)

```powershell
python -m bot.cli farm --level 50
python -m bot.cli farm --forever --energy-wait 60
python -m bot.cli play --games 5 --level 50
```

Only one `farm` / `play` run at a time.

### Arena tuning

```powershell
python -m bot.cli daily arena --force --arena-fights 5 --arena-max-power 4.5
python -m bot.cli daily arena --arena-exit-early
python -m bot.cli daily arena --arena-confirm --arena-confirm-wait 15
```

In a chain, add **Arena** and set **Fights** / **Max power (M)** on the step.

### Emulator control

```powershell
python -m bot.cli emulator status
python -m bot.cli emulator reconnect
python -m bot.cli emulator reboot
```

Panel: **Emulator & stop** section. **Reconnect** only fixes ADB; **Reboot** restarts the emulator and waits for lobby.

### Skill scores

The bot picks in-game skills by **score** (higher = preferred).

- Panel → **Skill scores** table: edit name, category, group, score.
- **Scan in-game** on skill select screen catalogs visible cards.
- CLI: `python -m bot.cli skills list`, `skills set dano/bolt 95`, `skills scan`.

Config: `config/skills.json`, catalog images in `templates/skills_catalog/`.

### Calibration & debugging

```powershell
python -m bot.cli calibrate --identify
python -m bot.cli calibrate --shot lobby.png
python -m bot.cli calibrate --read-floor
python -m bot.cli calibrate --read-arena-power
```

- **Identify screen** — what the bot thinks is on screen.
- Screenshots → `screenshots/`
- Logs → `logs/bot.log` (also in panel **Log & daily checks**)
- Failure dumps → `screenshots/dumps/`

### Configuration files

| Path | Purpose |
|------|---------|
| `.env` | Emulator path, ADB port, game package |
| `data/presets.json` | Your saved routine presets |
| `data/run-state.json` | Interrupted run (resume) |
| `config/coords.json` | Tap coordinates (900×1600) |
| `config/daily-claims.json` | Daily claim metadata & tiers |
| `config/skills.json` | Skill scores |
| `ARCHERO_DATA_DIR` | Optional: move `data/` elsewhere (portable setups) |

### Portable data folder

Set in `.env`:

```env
ARCHERO_DATA_DIR=D:\ArchHelper\data
```

Presets and run state then live in that folder.

### Testing with screenshots

```powershell
python -m bot.cli test flows
python -m bot.cli test flow arena
python -m bot.cli test vision arena/opponents_popup
```

### Tips

- Keep resolution **900×1600 portrait**; wrong resolution breaks taps.
- Put **Farm forever** last in a chain — it runs until you stop it.
- Use **Auto recovery** for long unattended chains.
- Guild legacy donate may need **Recover emulator** on the old daily options if loading hangs (rare).
