# v0.2.0

## Desktop panel (Windows)

- Ready-to-unzip release: `Install.cmd` + `Start-Panel.cmd`
- Non-technical guide: `release/INSTALLATION.md`
- Panel opens the browser automatically

## Bot

- **Arena**: picks rival #3–5 highest below `--arena-max-power`, Challenge per row, returns to lobby after N fights
- **Peak Arena**, **Rumble Ladder**, **Seal Battle**, **Monster Invasion**, **Magic Plant Defense** (survival mode with circle movement)
- **Rune Ruins** picks (`--rune-ruins-keys`)
- Screenshot tests (`python -m bot.cli test flows`)

## Requirements

- Windows 10/11, Python 3.12+, MuMu 12 (900×1600 portrait), Archero 2 + Play Services
