python -m bot.cli daily guild             # solo guild
python -m bot.cli daily shackled_jungle    # Events -> Dungeon -> Shackled Jungle
python -m bot.cli daily abyssal_tide       # Events -> Dungeon -> Abyssal Tide (AFK)
python -m bot.cli daily guild friends shop # varios en secuencia
```

`farm` repite partidas hasta que tocar Start ya no inicia combate (sin energía,
o aparece un popup de compra que el bot cierra sin gastar). `--max-games` es un
tope de seguridad para evitar loops infinitos.

Con `--forever` no se detiene al agotar la energía: cierra el popup sin gastar,
espera `--energy-wait` minutos (default **60**) y reintenta, indefinidamente.
La energía regenera ~1 cada 12 min y un run cuesta 5, así que ~60 min por
partida. Cortás con el archivo `STOP` o `Ctrl+C`.

### Shackled Jungle (Dungeon)

Combates en Events → Dungeon → Shackled Jungle. Solo elige skills (sin movimiento).
Derrota o victoria cuenta como run completado.

```bash
python -m bot.cli daily shackled_jungle --force
```

**Flujo (2 runs/día):**

| Paso | Acción | Coord |
|------|--------|-------|
| 1 | Events (nav inferior der) | `(797, 1523)` |
| 2 | Tab Dungeon | `(680, 1380)` |
| 3 | Banner Shackled Jungle | `(450, 900)` |
| 4 | Run 1: Start (ticket free) | `(450, 1264)` |
| 5 | Run 2: ticket ad (izq) + doble Start | `(320, 1100)` + `(450, 1264)` ×2 |
| 6 | Fin de run: tap empty (centro, debajo del grid) | `(450, 1552)` |
| 7 | Salir: back popup → Campaign | `menu.back` → `nav.campaign` |

**Skills:** rechaza pacto solo si el botón rojo Reject está visible. Si no,
elige la carta con mayor score según `config/skills.json`.

Coords en `events.shackled_jungle_*` en [config/coords.json](config/coords.json).

### Abyssal Tide (Dungeon)

Combates en Events → Dungeon → Abyssal Tide. Modo **AFK**: espera en combate (~1.5–4 min),
elige skill si aparece level-up, y vuelve al lobby de campaña.

```bash
python -m bot.cli daily abyssal_tide --force
```

**Flujo (2 free/día + ad si hay ticket video):**

| Paso | Acción | Coord |
|------|--------|-------|
| 1 | Events (nav inferior der) | `(797, 1523)` |
| 2 | Tab Dungeon | `(680, 1380)` |
| 3 | Banner Abyssal Tide | `(450, 1050)` |
| 4 | Run 1–2: Start (ticket free) | `(450, 1290)` |
| 5 | Run ad (si visible): ticket ad + doble Start | `(320, 1100)` + `(450, 1290)` ×2 |
| 6 | Fin de run: tap empty | `(450, 1552)` |
| 7 | Salir: back popup → Campaign | `menu.back` → `nav.campaign` |

Coords en `events.abyssal_tide_*` en [config/coords.json](config/coords.json).

### Selección del nivel 50 (a prueba de errores)

Antes de cada Start, el bot verifica por imagen que el título del nivel 50
("Fairytale Fortress") esté centrado. Si no lo está, lee el **piso actual** del
badge en el mapa y navega en la dirección correcta:

- piso **menor** que 50 → sube (49 → 50)
- piso **mayor** que 50 → baja

Solo si no puede leer el piso ni encontrarlo subiendo/bajando, hace el rescan
completo desde el piso 1. **Nunca presiona Start** si no confirma el nivel 50.

Calibrar lectura del badge (si falla): capturá el lobby en el mapa de campaña y
ajustá `lobby.campaign_floor_badge` en `coords.json`, o probá:

```bash
python -m bot.cli calibrate --read-floor
```

Para mejor lectura de todos los dígitos, podés recortar `templates/digits/0.png`
… `9.png` desde una captura del badge.

Otros comandos:

```bash
# Jugar un número fijo de partidas (manual)
python -m bot.cli play --games 5 --level 50

# Herramientas de calibración
python -m bot.cli calibrate --shot pantalla.png      # captura
python -m bot.cli calibrate --identify               # pantalla detectada
python -m bot.cli calibrate --tap 581,1130           # tap de prueba
python -m bot.cli calibrate --crop 74,648,170,150 --out templates/skills/dano/x.png
```

Post-run **Challenge has ended**: el bot detecta el banner por color, layout y (opcional) template.
Para máxima precisión, recortá el banner con la pantalla visible:

```bash
python -m bot.cli calibrate --crop 200,280,500,90 --out templates/anchors/challenge_ended.png
```

### Kill-switch (parada de emergencia)

- Crear un archivo vacío llamado `STOP` en la raíz del proyecto detiene el bot antes
  de la siguiente acción.
- `Ctrl+C` también lo corta de forma limpia.

## Selección de skills (sin IA)

Cada skill tiene ID `categoria/nombre` (template opcional en `templates/skills/`).
**Categorías:** Daño (`dano`), Utilidad (`utilidad`), Movilidad (`movilidad`), Atk Speed (`atk_speed`).
**Grupos:** Meteoro, Planta, Elemental, Sprite, Circulos, Swords, MainWeapon — se asignan en el panel y viven en `groups_map`.

In-game el bot elige la carta con mayor score. Ya **no** intenta detectar/catalogar activos;
solo rechaza pactos si el botón rojo Reject está visible.

### Puntajes

```bash
python -m bot.cli skills list
python -m bot.cli skills set dano/piercing_arrow 100
python -m bot.cli skills bump dano/bolt 5
python -m bot.cli skills scan
```

Los scores viven en [config/skills.json](config/skills.json) → `scores`. Skills sin
score manual usan `category_defaults`.

**Desde el panel:** editá nombre, categoría, **grupo** y score → **Guardar** (copia el PNG del catálogo a `templates/skills/` automáticamente). **Scan in-game** cataloga cartas visibles en `skills-catalog.json`;

Para etiquetar en lote contra el [wiki de Skills](https://archero-2.game-vault.net/wiki/Skills):

```bash
python scripts/label_skills_from_wiki.py
```

Descarga íconos del wiki, compara con `templates/skills_catalog/` y completa nombres, categorías y grupos.
durante farm/play también se cataloga cada skill select automáticamente. Entradas
`catalog/...` son skills sin identificar aún — etiquetalas en el panel (Guardar) o
movelas manualmente a `templates/skills/<cat>/`.

El panel muestra la **pantalla actual** (lobby, battle, skill_select, …) y antes de
cada tarea vuelve al **lobby de campaña**; si estás en combate activo no interrumpe
(salvo que lances otra tarea de menú — ahí avisa y no arranca).

Configurable en `skills.json`:

- `selection_mode`: `score` (default) o `category` (orden por categoría, modo anterior).
- `avoid`: categorías a evitar (ej. `utilidad`).
- `match_threshold`: confianza mínima del template match.
- `devil_deal`: `reject` (default) o `sign`. Los tratos del diablo cuestan Max HP.

Funcionamiento: en cada level-up se detectan las cartas (2 o 3), se matchean contra
los templates y se elige la de **mayor puntaje**. Las cartas sin match confiable se
guardan en `templates/unknown_skills/` para etiquetar: movelas a
`templates/skills/<categoria>/` y asignales score con `skills set`.

## Failsafes

- **MoneyGuard**: nunca toca botones con etiqueta de precio en dinero real (`templates/buttons/money_tag.png`).
- **StuckDetector**: detecta pantallas congeladas y dispara recovery.
- **UnknownScreenWatchdog**: aborta el path si la pantalla queda irreconocible demasiado tiempo.
- **BattleTimeout:** corta una partida que excede su duración máxima (default 200s; usar `--battle-timeout 480` para runs de 50 waves).
- **Kill-switch:** archivo `STOP` + `Ctrl+C`.
- Tras victoria/derrota el bot espera hasta 75s en pantallas de carga/transición antes de volver al lobby.
- Logs en `logs/bot.log`; dumps de captura ante error en `screenshots/dumps/`.

### Emulador colgado (loading infinito)

A veces el emulador se queda congelado (p. ej. popup "Ongoing guild tech donations"):
los taps por ADB dejan de tener efecto y **solo reiniciar el emulador** lo desbloquea.

**Manual:**

```bash
python -m bot.cli emulator reboot
```

**Automático (opcional):** con `--recover-emulator` el bot detecta loading colgado en
Guild Legacy, reinicia el emulador, espera ADB + lobby y reintenta **una vez**
por sesión:

```bash
python -m bot.cli daily guild --force --recover-emulator
```

Estado del emulador: `python -m bot.cli emulator status`
Reconectar ADB: `python -m bot.cli emulator reconnect`

## Calibración

Las coords viven en [config/coords.json](config/coords.json) (espacio 900x1600). Un
punto en `0,0` está sin calibrar y se omite/avisa en vez de romper el flujo. Para
calibrar un punto: poné el juego en la pantalla correspondiente, capturá con
`calibrate --shot`, abrí la imagen, leé el pixel y editá el JSON. Para templates usá
`calibrate --crop X,Y,W,H --out ruta.png`.

Anchors de pantalla en `templates/anchors/` (lobby, battle_hud, skill_select,
devil_deal, victory, defeat). Si falta un anchor, esa pantalla simplemente no se
detecta (no rompe).

## Estructura

```
bot/
  device.py    # ADB: screenshot()->np.array, tap, swipe, back, key
  vision.py    # template matching multiescala, detección de cartas, diffs
  screens.py   # identify() -> ScreenId por anchors
  skills.py    # SkillPicker (match + puntaje)
  skill_scores.py # list/set/bump de puntajes
  failsafes.py # MoneyGuard, StuckDetector, watchdogs, kill-switch, BattleTimeout
  emulator.py  # MuMuManager / ldconsole: launch, reboot, runapp, ADB
  ldplayer.py    # alias legacy de emulator.py
  recovery.py    # reboot emulador y esperar lobby tras hang
  configs.py   # carga de config/coords.json y config/skills.json
  log.py       # logging + dumps
  paths/
    base.py        # contexto compartido + helpers
    daily.py       # flujo diario validado
    play_level.py  # jugar N partidas (entrar, x3, esquivar, skills, fin de run)
  cli.py       # launcher: daily | play | calibrate | panel
  panel/       # panel web local (HTTP + botones)
config/        # coords.json, skills.json, daily-claims.json, skills-catalog.json
templates/     # anchors/, buttons/, skills/<categoria>/, skills_catalog/
scripts/       # utilidades (label_skills_from_wiki, calib_autofight)
uploads/       # datos opcionales para scripts (Skills-0.md del wiki)
```

## Notas

- Si cambiás la resolución del emulador, recalibrá coords y anchors.
- Usar bots puede violar los TOS del juego — úsalo bajo tu responsabilidad.
- El bot nunca gasta dinero real ni moneda de evento sin tu indicación.
