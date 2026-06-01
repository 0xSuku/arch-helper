"""Launcher del bot.

Dos bots principales:
  python -m bot.cli farm                 # gasta toda la energía jugando el nivel 50
  python -m bot.cli daily                # todos los claims
  python -m bot.cli daily guild          # solo guild
  python -m bot.cli daily guild friends shop   # varios a la vez
  python -m bot.cli daily --list         # lista claims disponibles

Otros:
  python -m bot.cli play --games 5 --level 50   # jugar N partidas manuales
  python -m bot.cli calibrate --shot lobby.png
  python -m bot.cli calibrate --identify
  python -m bot.cli calibrate --tap 581,1130
  python -m bot.cli calibrate --crop 120,300,180,180 --out templates/skills/dano/atk.png
  python -m bot.cli skills list
  python -m bot.cli skills set dano/piercing_arrow 95
  python -m bot.cli skills bump dano/bolt 5
  python -m bot.cli skills scan
  python -m bot.cli panel                  # panel web con botones
"""
from __future__ import annotations

import argparse
import sys

import cv2

from . import screens, vision
from .configs import Coords
from .device import Device
from .failsafes import StopRequested, clear_stop_file
from .log import get_logger
from .paths.base import BotContext
from .daily_checks import DailyChecks
from .paths.daily import MAIN_LOOP_ORDER, DailyPath
from .paths.play_level import PlayLevelPath

log = get_logger("cli")


def _connect() -> Device:
    from .recovery import reconnect_adb

    device = Device()
    if not reconnect_adb(device):
        log.error(
            "ADB no conectado a %s. Verifica que el emulador este abierto y proba: "
            "python -m bot.cli emulator reconnect",
            device.serial,
        )
        sys.exit(2)
    log.info("Conectado a %s", device.serial)
    return device


def _parse_xy(text: str) -> tuple[int, int]:
    x, y = text.split(",")
    return int(x), int(y)


def cmd_daily(args: argparse.Namespace) -> None:
    if args.status:
        for line in DailyChecks(force=False).status_lines():
            print(line)
        return
    if args.reset_checks is not None:
        DailyChecks(force=True).unmark(None if args.reset_checks == "all" else args.reset_checks)
        return
    if args.list:
        print("Claims disponibles (* = loop principal):")
        for name in DailyPath.available_claims():
            tag = "*" if name in MAIN_LOOP_ORDER else " "
            print(f"  {tag} {name}")
        print("\nSin args = loop principal. --force ignora checks verificados.")
        print("Alias: mail, island, angler, sidebar, all, tasks, friends")
        return
    device = _connect()
    ctx = BotContext(device)
    explicit = bool(args.claims)
    path = DailyPath(
        ctx,
        force=args.force or explicit,
        recover_emulator=args.recover_emulator,
    )
    if args.mark:
        path.mark_verified(args.mark)
        print(f"Marcado verificado: {args.mark}")
        return
    try:
        path.run(args.claims or None)
    except ValueError as exc:
        log.error("%s", exc)
        sys.exit(2)


def cmd_play(args: argparse.Namespace) -> None:
    device = _connect()
    ctx = BotContext(device)
    PlayLevelPath(
        ctx,
        level=args.level,
        games=args.games,
        battle_timeout=args.battle_timeout,
        dodge=args.dodge,
    ).run()


def cmd_farm(args: argparse.Namespace) -> None:
    from .navigation import prepare_for_task

    device = _connect()
    ctx = BotContext(device)
    prepare_for_task(ctx, "farm")
    PlayLevelPath(
        ctx,
        level=args.level,
        games=None,
        battle_timeout=args.battle_timeout,
        max_games=args.max_games,
        forever=args.forever,
        energy_wait_s=args.energy_wait * 60.0,
        dodge=args.dodge,
    ).run()


def cmd_calibrate(args: argparse.Namespace) -> None:
    device = _connect()
    if args.shot:
        device.screenshot(save_as=args.shot)
        log.info("Captura guardada en screenshots/%s", args.shot)
    if args.identify:
        sid = screens.identify(device.screenshot())
        log.info("Pantalla actual: %s", sid.value)
    if args.tap:
        x, y = _parse_xy(args.tap)
        device.tap(x, y)
        log.info("Tap enviado a (%d,%d)", x, y)
    if args.crop and args.out:
        x, y, w, h = (int(p) for p in args.crop.split(","))
        region = vision.crop(device.screenshot(), (x, y, w, h))
        cv2.imwrite(args.out, region)
        log.info("Template recortado (%d,%d,%d,%d) -> %s", x, y, w, h, args.out)
    if args.read_floor:
        try:
            region = Coords.load().region("lobby", "campaign_floor_badge")
        except (KeyError, ValueError):
            region = vision.DEFAULT_CAMPAIGN_FLOOR_BADGE
        floor = vision.read_campaign_floor_badge(device.screenshot(), region)
        print(f"Piso leído: {floor if floor is not None else '(no legible)'}")


def cmd_skills(args: argparse.Namespace) -> None:
    from .screens import ScreenId
    from .skill_scores import (
        bump_score,
        format_skill_table,
        list_skill_rows,
        resolve_skill_id,
        set_score,
    )
    from .skills import SkillPicker

    if args.action == "list":
        print(format_skill_table(list_skill_rows()))
        return

    if args.action == "set":
        skill_id = resolve_skill_id(args.skill_id)
        set_score(skill_id, args.score)
        print(f"{skill_id} -> {args.score}")
        return

    if args.action == "bump":
        skill_id = resolve_skill_id(args.skill_id)
        new_score = bump_score(skill_id, args.delta)
        print(f"{skill_id} -> {new_score} ({args.delta:+d})")
        return

    if args.action == "scan":
        device = _connect()
        screen = device.screenshot()
        sid = screens.identify(screen)
        if sid != ScreenId.SKILL_SELECT:
            log.warning("Pantalla actual: %s (esperaba skill_select)", sid.value)
        picker = SkillPicker()
        try:
            coords = Coords.load()
            fallback = coords.regions("skill_select", "cards")
        except (KeyError, ValueError):
            fallback = None
        regions = picker.detect_cards(screen)
        if len(regions) < 2 and fallback:
            regions = fallback
        evaluations = picker.evaluate(screen, regions, catalog=True)
        if not evaluations:
            print("No se detectaron cartas.")
            sys.exit(1)
        print(f"Catalogadas {len(evaluations)} cartas visibles en config/skills-catalog.json")
        print("Cartas en pantalla (orden de elección del bot):")
        if picker.selection_mode == "score":
            ranked = sorted(evaluations, key=lambda e: (-e.score, -e.confidence))
        else:
            ranked = sorted(evaluations, key=lambda e: (picker._rank(e.category), -e.confidence))
        for i, ev in enumerate(ranked, 1):
            mark = " <-- elegiría" if i == 1 else ""
            print(
                f"  {i}. carta {ev.index}: {ev.skill_id} score={ev.score} "
                f"conf={ev.confidence:.2f}{mark}"
            )
        return

    log.error("Acción desconocida: %s", args.action)
    sys.exit(2)


def cmd_emulator(args: argparse.Namespace) -> None:
    from .emulator import EmulatorConsole
    from .recovery import adb_status, reboot_emulator_and_wait_lobby, reconnect_adb

    console = EmulatorConsole()
    if not console.tool.exists():
        log.error("No se encontro %s", console.tool)
        sys.exit(2)

    device = Device()

    if args.action == "reconnect":
        if reconnect_adb(device):
            print(f"ADB {device.serial}: reconectado")
            return
        print(
            f"Si sigue fallando: verifica ADB en {console.display_name} "
            f"o reinicia el emulador y reintenta reconnect."
        )
        sys.exit(1)

    if args.action == "reboot":
        if not reboot_emulator_and_wait_lobby(device):
            sys.exit(1)
        return

    if args.action == "status":
        st = adb_status(device)
        print(f"{st['emulator']} index {console.index}: {'running' if st['running'] else 'stopped'}")
        print(f"Puerto {st['serial']}: {'abierto' if st['port_open'] else 'cerrado (ADB daemon apagado)'}")
        print(f"ADB devices: {'conectado' if st['adb_listed'] else 'desconectado'}")
        if st["running"] and not st["port_open"]:
            print("-> Proba: python -m bot.cli emulator reconnect")
        return

    log.error("Accion desconocida: %s", args.action)
    sys.exit(2)


cmd_ldplayer = cmd_emulator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bot", description="Bot Archero v2 (no-IA)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser("daily", help="Claims diarios (uno, varios o todos)")
    p_daily.add_argument(
        "claims",
        nargs="*",
        metavar="CLAIM",
        help="Claims a ejecutar (sin args = todos). Ej: guild friends shop",
    )
    p_daily.add_argument("--list", action="store_true", help="Lista claims disponibles")
    p_daily.add_argument("--status", action="store_true", help="Muestra checks verificados del periodo")
    p_daily.add_argument("--force", action="store_true", help="Ignora checks verificados y corre igual")
    p_daily.add_argument("--mark", metavar="CLAIM", help="Marca un claim como verificado/cerrado")
    p_daily.add_argument(
        "--reset-checks",
        metavar="CLAIM|all",
        help="Resetea check verificado de un claim o todos",
    )
    p_daily.add_argument(
        "--recover-emulator",
        "--recover-ldplayer",
        action="store_true",
        dest="recover_emulator",
        help="Si el emulador se cuelga (loading infinito), lo reinicia y reintenta una vez",
    )
    p_daily.set_defaults(func=cmd_daily)

    p_emu = sub.add_parser("emulator", help="Control del emulador (MuMu / LDPlayer)")
    p_emu.add_argument(
        "action",
        choices=("reconnect", "reboot", "status"),
        help="reconnect: solo ADB (no pierde partida); reboot: reinicia emulador; status: estado",
    )
    p_emu.set_defaults(func=cmd_emulator)

    p_ld = sub.add_parser("ldplayer", help="Alias de emulator (legacy LDPlayer)")
    p_ld.add_argument(
        "action",
        choices=("reconnect", "reboot", "status"),
        help="reconnect: solo ADB (no pierde partida); reboot: reinicia emulador; status: estado",
    )
    p_ld.set_defaults(func=cmd_ldplayer)

    p_farm = sub.add_parser("farm", help="Bot de energía: juega el nivel hasta agotar la energía")
    p_farm.add_argument("--level", type=int, default=50)
    p_farm.add_argument("--battle-timeout", type=float, default=600.0)
    p_farm.add_argument("--max-games", type=int, default=40, help="Tope de seguridad (sin --forever)")
    p_farm.add_argument(
        "--forever",
        action="store_true",
        help="Modo infinito: al quedarse sin energía, espera y reintenta",
    )
    p_farm.add_argument(
        "--energy-wait",
        type=float,
        default=60.0,
        help="Minutos a esperar por energía entre reintentos (con --forever). "
        "Regenera ~1 energía/12 min y un run cuesta 5, así que ~60 min por partida.",
    )
    p_farm.add_argument(
        "--dodge",
        action="store_true",
        help="Reactiva el esquive continuo (por defecto: solo agarra la ruleta y se queda quieto)",
    )
    p_farm.set_defaults(func=cmd_farm)

    p_play = sub.add_parser("play", help="Juega N partidas de un nivel (manual)")
    p_play.add_argument("--games", type=int, default=1)
    p_play.add_argument("--level", type=int, default=50)
    p_play.add_argument("--battle-timeout", type=float, default=600.0)
    p_play.add_argument(
        "--dodge",
        action="store_true",
        help="Reactiva el esquive continuo (por defecto: solo agarra la ruleta y se queda quieto)",
    )
    p_play.set_defaults(func=cmd_play)

    p_cal = sub.add_parser("calibrate", help="Herramientas de calibración")
    p_cal.add_argument("--shot", metavar="NOMBRE.png", help="Captura la pantalla")
    p_cal.add_argument("--identify", action="store_true", help="Imprime la pantalla detectada")
    p_cal.add_argument("--tap", metavar="X,Y", help="Envía un tap de prueba")
    p_cal.add_argument("--crop", metavar="X,Y,W,H", help="Recorta una región de la captura")
    p_cal.add_argument("--out", metavar="RUTA.png", help="Destino del recorte de --crop")
    p_cal.add_argument("--read-floor", action="store_true", help="Lee el piso actual del badge del mapa campaña")
    p_cal.set_defaults(func=cmd_calibrate)

    p_sk = sub.add_parser("skills", help="Puntajes por skill para elección in-game")
    sk_sub = p_sk.add_subparsers(dest="action", required=True)

    p_sk_list = sk_sub.add_parser("list", help="Lista templates y puntajes")
    p_sk_list.set_defaults(func=cmd_skills)

    p_sk_set = sk_sub.add_parser("set", help="Asigna puntaje a un skill (ID: categoria/nombre)")
    p_sk_set.add_argument("skill_id", help="Ej: dano/bolt o solo bolt si es único")
    p_sk_set.add_argument("score", type=int, help="Puntaje (mayor = más preferido)")
    p_sk_set.set_defaults(func=cmd_skills)

    p_sk_bump = sk_sub.add_parser("bump", help="Suma delta al puntaje actual")
    p_sk_bump.add_argument("skill_id")
    p_sk_bump.add_argument("delta", type=int, nargs="?", default=1)
    p_sk_bump.set_defaults(func=cmd_skills)

    p_sk_scan = sk_sub.add_parser("scan", help="Analiza la pantalla de skill select actual")
    p_sk_scan.set_defaults(func=cmd_skills)

    p_panel = sub.add_parser("panel", help="Panel web local con botones (farm, daily, emulador)")
    p_panel.add_argument("--host", default="127.0.0.1")
    p_panel.add_argument("--port", type=int, default=8765)
    p_panel.set_defaults(func=cmd_panel)

    return parser


def cmd_panel(args: argparse.Namespace) -> None:
    from .panel.server import run_panel

    run_panel(host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    clear_stop_file()
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except StopRequested as exc:
        log.warning("Detenido: %s", exc)
    except KeyboardInterrupt:
        log.warning("Interrumpido por el usuario (Ctrl+C)")


if __name__ == "__main__":
    main()
