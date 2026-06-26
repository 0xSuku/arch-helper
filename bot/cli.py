"""Bot launcher.

Main bots:
  python -m bot.cli run 5-arena-farm          # saved preset
  python -m bot.cli run arena:5 farm:forever  # inline chain
  python -m bot.cli run --resume              # resume after recovery
  python -m bot.cli presets list              # view/save presets

Also:
  python -m bot.cli farm                 # spend all energy playing level 50
  python -m bot.cli daily                # all claims
  python -m bot.cli daily guild          # guild only
  python -m bot.cli daily guild friends shop   # several at once
  python -m bot.cli daily --list         # list available claims

Other:
  python -m bot.cli play --games 5 --level 50   # play N manual games
  python -m bot.cli calibrate --shot lobby.png
  python -m bot.cli calibrate --identify
  python -m bot.cli calibrate --tap 581,1130
  python -m bot.cli calibrate --crop 120,300,180,180 --out templates/skills/dano/atk.png
  python -m bot.cli skills list
  python -m bot.cli skills set dano/piercing_arrow 95
  python -m bot.cli skills bump dano/bolt 5
  python -m bot.cli skills scan
  python -m bot.cli panel                  # local web panel with buttons
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
            "ADB not connected to %s. Verify the emulator is open and try: "
            "python -m bot.cli emulator reconnect",
            device.serial,
        )
        sys.exit(2)
    log.info("Connected to %s", device.serial)
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
        print("Available claims (* = main loop):")
        for name in DailyPath.available_claims():
            tag = "*" if name in MAIN_LOOP_ORDER else " "
            print(f"  {tag} {name}")
        print("\nNo args = main loop. --force ignores verified checks.")
        print("Aliases: mail, island, angler, sidebar, all, tasks, friends")
        return
    device = _connect()
    ctx = BotContext(device)
    explicit = bool(args.claims)
    path = DailyPath(
        ctx,
        force=args.force or explicit,
        recover_emulator=args.recover_emulator,
        arena_fights=getattr(args, "arena_fights", None),
        arena_max_power=getattr(args, "arena_max_power", None),
        arena_exit_early=getattr(args, "arena_exit_early", False),
        arena_confirm=getattr(args, "arena_confirm", False),
        arena_confirm_wait=getattr(args, "arena_confirm_wait", None),
        arena_battle_abort_s=getattr(args, "arena_battle_abort_s", None),
        arena_reload_after_exit_s=getattr(args, "arena_reload_after_exit_s", None),
        rune_ruins_keys=getattr(args, "rune_ruins_keys", None),
    )
    if args.mark:
        path.mark_verified(args.mark)
        print(f"Marked verified: {args.mark}")
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
        log.info("Screenshot saved to screenshots/%s", args.shot)
    if args.identify:
        sid = screens.identify(device.screenshot())
        log.info("Current screen: %s", sid.value)
    if args.tap:
        x, y = _parse_xy(args.tap)
        device.tap(x, y)
        log.info("Tap sent to (%d,%d)", x, y)
    if args.crop and args.out:
        x, y, w, h = (int(p) for p in args.crop.split(","))
        region = vision.crop(device.screenshot(), (x, y, w, h))
        cv2.imwrite(args.out, region)
        log.info("Template cropped (%d,%d,%d,%d) -> %s", x, y, w, h, args.out)
    if args.read_floor:
        try:
            region = Coords.load().region("lobby", "campaign_floor_badge")
        except (KeyError, ValueError):
            region = vision.DEFAULT_CAMPAIGN_FLOOR_BADGE
        floor = vision.read_campaign_floor_badge(device.screenshot(), region)
        print(f"Floor read: {floor if floor is not None else '(unreadable)'}")
    if getattr(args, "read_arena_power", False):
        screen = device.screenshot()
        power = vision.read_arena_opponent_power(screen, 2)
        rows = vision.find_arena_power_row_ys(screen)
        print(f"Detected rows Y={rows}")
        print(f"Opponent #3 power: {power if power is not None else '(unreadable)'}M")


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
            log.warning("Current screen: %s (expected skill_select)", sid.value)
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
            print("No cards detected.")
            sys.exit(1)
        print(f"Cataloged {len(evaluations)} visible cards in config/skills-catalog.json")
        print("Cards on screen (bot pick order):")
        if picker.selection_mode == "score":
            ranked = sorted(evaluations, key=lambda e: (-e.score, -e.confidence))
        else:
            ranked = sorted(evaluations, key=lambda e: (picker._rank(e.category), -e.confidence))
        for i, ev in enumerate(ranked, 1):
            mark = " <-- would pick" if i == 1 else ""
            print(
                f"  {i}. card {ev.index}: {ev.skill_id} score={ev.score} "
                f"conf={ev.confidence:.2f}{mark}"
            )
        return

    log.error("Unknown action: %s", args.action)
    sys.exit(2)


def cmd_emulator(args: argparse.Namespace) -> None:
    from .emulator import EmulatorConsole
    from .recovery import adb_status, reboot_emulator_and_wait_lobby, reconnect_adb

    console = EmulatorConsole()
    if not console.tool.exists():
        log.error("Could not find %s", console.tool)
        sys.exit(2)

    device = Device()

    if args.action == "reconnect":
        if reconnect_adb(device):
            print(f"ADB {device.serial}: reconnected")
            return
        print(
            f"If it still fails: verify ADB in {console.display_name} "
            f"or restart the emulator and retry reconnect."
        )
        sys.exit(1)

    if args.action == "reboot":
        if not reboot_emulator_and_wait_lobby(device):
            sys.exit(1)
        return

    if args.action == "status":
        st = adb_status(device)
        print(f"{st['emulator']} index {console.index}: {'running' if st['running'] else 'stopped'}")
        print(f"Port {st['serial']}: {'open' if st['port_open'] else 'closed (ADB daemon off)'}")
        print(f"ADB devices: {'connected' if st['adb_listed'] else 'disconnected'}")
        if st["running"] and not st["port_open"]:
            print("-> Try: python -m bot.cli emulator reconnect")
        return

    log.error("Unknown action: %s", args.action)
    sys.exit(2)


cmd_ldplayer = cmd_emulator


def cmd_run(args: argparse.Namespace) -> None:
    from .actions import parse_inline_step
    from .pipeline import (
        PipelineRunner,
        build_state_from_preset,
        build_state_from_steps,
        clear_state,
        load_state,
    )
    from .presets import format_preset_table, get_preset, list_presets

    if args.clear_state:
        clear_state()
        print("Execution state cleared.")
        return

    if args.status:
        state = load_state()
        if state is None:
            print("No pending execution.")
            return
        print(f"Pipeline: {state.preset_name}")
        print(f"Current index: {state.current_index + 1}/{len(state.steps)}")
        for i, step_state in enumerate(state.steps, 1):
            label = step_state.step.get("action", "?")
            if step_state.step.get("name"):
                label = str(step_state.step["name"])
            err = f" — {step_state.error}" if step_state.error else ""
            print(f"  {i}. [{step_state.status}] {label}{err}")
        return

    if args.list:
        print("Available presets (data/presets.json):")
        print(format_preset_table())
        print("\nInline: python -m bot.cli run arena:5 farm:forever shackled:2")
        print("Resume: python -m bot.cli run --resume")
        return

    device = _connect()
    ctx = BotContext(device)
    runner = PipelineRunner(ctx)

    if args.resume:
        state = load_state()
        if state is None:
            log.error("No saved state. Run a preset or chain first.")
            sys.exit(2)
        try:
            runner.run(state, resume=True)
        except Exception as exc:  # noqa: BLE001
            log.error("%s", exc)
            log.info("Retry with: python -m bot.cli run --resume")
            sys.exit(1)
        return

    if args.items:
        if len(args.items) == 1 and get_preset(args.items[0]) is not None:
            preset = get_preset(args.items[0])
            assert preset is not None
            state = build_state_from_preset(preset)
            if args.no_recover:
                state.recover_on_failure = False
        else:
            inline_steps = [parse_inline_step(s) for s in args.items]
            state = build_state_from_steps(
                inline_steps,
                name=" ".join(args.items),
                recover_on_failure=not args.no_recover,
            )
    else:
        log.error("Specify a preset or inline steps. Use: python -m bot.cli run --list")
        sys.exit(2)

    try:
        runner.run(state, resume=False)
    except Exception as exc:  # noqa: BLE001
        log.error("%s", exc)
        log.info("State saved. Recovery: python -m bot.cli run --resume")
        sys.exit(1)


def cmd_presets(args: argparse.Namespace) -> None:
    import json

    from .actions import normalize_steps
    from .presets import delete_preset, format_preset_table, get_preset, list_presets, save_preset

    if args.action == "list":
        print(format_preset_table())
        return

    if args.action == "show":
        preset = get_preset(args.preset_id)
        if preset is None:
            log.error("Preset not found: %s", args.preset_id)
            sys.exit(2)
        print(json.dumps(preset.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.action == "save":
        if args.from_file:
            raw = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
            steps = raw.get("steps", raw)
            name = args.name or raw.get("name", args.preset_id)
            description = args.description or raw.get("description", "")
            recover = raw.get("recover_on_failure", not args.no_recover)
        else:
            if not args.steps:
                log.error("Specify steps: presets save ID --steps arena:5 farm:forever")
                sys.exit(2)
            steps = args.steps
            name = args.name or args.preset_id
            description = args.description or ""
            recover = not args.no_recover
        preset = save_preset(
            args.preset_id,
            name=name,
            description=description,
            steps=normalize_steps(steps),
            recover_on_failure=recover,
            overwrite=args.overwrite,
        )
        print(f"Saved preset {preset.id!r} ({len(preset.steps)} steps)")
        return

    if args.action == "delete":
        if not delete_preset(args.preset_id):
            log.error("Preset not found: %s", args.preset_id)
            sys.exit(2)
        print(f"Deleted preset {args.preset_id!r}")
        return

    log.error("Unknown action: %s", args.action)
    sys.exit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bot", description="Archero v2 bot (non-AI)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser("daily", help="Daily claims (one, several, or all)")
    p_daily.add_argument(
        "claims",
        nargs="*",
        metavar="CLAIM",
        help="Claims to run (no args = all). E.g.: guild friends shop",
    )
    p_daily.add_argument("--list", action="store_true", help="List available claims")
    p_daily.add_argument("--status", action="store_true", help="Show verified checks for the period")
    p_daily.add_argument("--force", action="store_true", help="Ignore verified checks and run anyway")
    p_daily.add_argument("--mark", metavar="CLAIM", help="Mark a claim as verified/closed")
    p_daily.add_argument(
        "--reset-checks",
        metavar="CLAIM|all",
        help="Reset verified check for a claim or all",
    )
    p_daily.add_argument(
        "--recover-emulator",
        "--recover-ldplayer",
        action="store_true",
        dest="recover_emulator",
        help="If the emulator hangs (infinite loading), restart it and retry once",
    )
    p_daily.add_argument(
        "--arena-fights",
        type=int,
        default=None,
        metavar="N",
        help="Arena fights per run (default 2). Only applies to arena/events claim.",
    )
    p_daily.add_argument(
        "--arena-max-power",
        type=float,
        default=None,
        metavar="M",
        help="Max opponent power in millions (default 5.0). Only fights opponents below.",
    )
    p_daily.add_argument(
        "--arena-exit-early",
        action="store_true",
        help="Arena: after ~10s in combat, pause -> Exit Battle -> Confirm (don't play to the end).",
    )
    p_daily.add_argument(
        "--arena-confirm",
        action="store_true",
        help="Arena: re-read opponents, save screenshot, and pause before each Challenge.",
    )
    p_daily.add_argument(
        "--arena-confirm-wait",
        type=float,
        default=None,
        metavar="SEC",
        help="Wait seconds with --arena-confirm (default 15). 0 = interactive prompt.",
    )
    p_daily.add_argument(
        "--arena-battle-abort-s",
        type=float,
        default=None,
        metavar="SEC",
        help="Seconds in combat before Exit Battle (default 10, with --arena-exit-early).",
    )
    p_daily.add_argument(
        "--arena-reload-after-exit-s",
        type=float,
        default=None,
        metavar="SEC",
        help="Wait after leaving combat before the next Challenge (default 5).",
    )
    p_daily.add_argument(
        "--rune-ruins-keys",
        type=int,
        default=None,
        metavar="N",
        help="Keys to spend in Rune Ruins (multiple of 5). E.g.: 30 = 6 x5.",
    )
    p_daily.set_defaults(func=cmd_daily)

    p_test = sub.add_parser("test", help="Testing with screenshots (fixtures)")
    p_test.add_argument(
        "action",
        choices=("list", "capture", "vision", "flows", "flow"),
        help="list/capture/vision/flows/flow",
    )
    p_test.add_argument("name", nargs="?", help="Fixture name or flow id")
    p_test.add_argument(
        "--live",
        action="store_true",
        help="With flow: run on connected emulator",
    )
    p_test.set_defaults(func=cmd_test)

    p_emu = sub.add_parser("emulator", help="Emulator control (MuMu / LDPlayer)")
    p_emu.add_argument(
        "action",
        choices=("reconnect", "reboot", "status"),
        help="reconnect: ADB only (doesn't lose match); reboot: restart emulator; status: state",
    )
    p_emu.set_defaults(func=cmd_emulator)

    p_ld = sub.add_parser("ldplayer", help="Alias for emulator (legacy LDPlayer)")
    p_ld.add_argument(
        "action",
        choices=("reconnect", "reboot", "status"),
        help="reconnect: ADB only (doesn't lose match); reboot: restart emulator; status: state",
    )
    p_ld.set_defaults(func=cmd_ldplayer)

    p_farm = sub.add_parser("farm", help="Energy bot: play the level until energy runs out")
    p_farm.add_argument("--level", type=int, default=50)
    p_farm.add_argument("--battle-timeout", type=float, default=600.0)
    p_farm.add_argument("--max-games", type=int, default=40, help="Safety cap (without --forever)")
    p_farm.add_argument(
        "--forever",
        action="store_true",
        help="Infinite mode: when out of energy, wait and retry",
    )
    p_farm.add_argument(
        "--energy-wait",
        type=float,
        default=60.0,
        help="Minutes to wait for energy between retries (with --forever). "
        "Regenerates ~1 energy/12 min and a run costs 5, so ~60 min per game.",
    )
    p_farm.add_argument(
        "--dodge",
        action="store_true",
        help="Re-enable continuous dodging (default: only grab the wheel and stay still)",
    )
    p_farm.set_defaults(func=cmd_farm)

    p_play = sub.add_parser("play", help="Play N games at a level (manual)")
    p_play.add_argument("--games", type=int, default=1)
    p_play.add_argument("--level", type=int, default=50)
    p_play.add_argument("--battle-timeout", type=float, default=600.0)
    p_play.add_argument(
        "--dodge",
        action="store_true",
        help="Re-enable continuous dodging (default: only grab the wheel and stay still)",
    )
    p_play.set_defaults(func=cmd_play)

    p_cal = sub.add_parser("calibrate", help="Calibration tools")
    p_cal.add_argument("--shot", metavar="NAME.png", help="Capture the screen")
    p_cal.add_argument("--identify", action="store_true", help="Print the detected screen")
    p_cal.add_argument("--tap", metavar="X,Y", help="Send a test tap")
    p_cal.add_argument("--crop", metavar="X,Y,W,H", help="Crop a region from the screenshot")
    p_cal.add_argument("--out", metavar="PATH.png", help="Destination for --crop output")
    p_cal.add_argument("--read-floor", action="store_true", help="Read current floor from campaign map badge")
    p_cal.add_argument("--read-arena-power", action="store_true", help="Read opponent #3 power in Arena popup")
    p_cal.set_defaults(func=cmd_calibrate)

    p_sk = sub.add_parser("skills", help="Per-skill scores for in-game selection")
    sk_sub = p_sk.add_subparsers(dest="action", required=True)

    p_sk_list = sk_sub.add_parser("list", help="List templates and scores")
    p_sk_list.set_defaults(func=cmd_skills)

    p_sk_set = sk_sub.add_parser("set", help="Assign score to a skill (ID: category/name)")
    p_sk_set.add_argument("skill_id", help="E.g.: dano/bolt or just bolt if unique")
    p_sk_set.add_argument("score", type=int, help="Score (higher = more preferred)")
    p_sk_set.set_defaults(func=cmd_skills)

    p_sk_bump = sk_sub.add_parser("bump", help="Add delta to current score")
    p_sk_bump.add_argument("skill_id")
    p_sk_bump.add_argument("delta", type=int, nargs="?", default=1)
    p_sk_bump.set_defaults(func=cmd_skills)

    p_sk_scan = sk_sub.add_parser("scan", help="Analyze the current skill select screen")
    p_sk_scan.set_defaults(func=cmd_skills)

    p_panel = sub.add_parser("panel", help="Local web panel with buttons (farm, daily, emulator)")
    p_panel.add_argument("--host", default="127.0.0.1")
    p_panel.add_argument("--port", type=int, default=8765)
    p_panel.set_defaults(func=cmd_panel)

    p_run = sub.add_parser("run", help="Run action chain (preset or inline)")
    p_run.add_argument(
        "items",
        nargs="*",
        metavar="PRESET|STEP",
        help="Preset ID or inline steps (arena:5 farm:forever)",
    )
    p_run.add_argument("--list", action="store_true", help="List available presets")
    p_run.add_argument("--resume", action="store_true", help="Resume from saved state (after recovery)")
    p_run.add_argument("--status", action="store_true", help="Show pending execution state")
    p_run.add_argument("--clear-state", action="store_true", help="Clear saved state")
    p_run.add_argument(
        "--no-recover",
        action="store_true",
        help="Don't restart emulator/game automatically if a step fails",
    )
    p_run.set_defaults(func=cmd_run)

    p_presets = sub.add_parser("presets", help="Manage saved presets")
    pr_sub = p_presets.add_subparsers(dest="action", required=True)

    p_pr_list = pr_sub.add_parser("list", help="List presets")
    p_pr_list.set_defaults(func=cmd_presets)

    p_pr_show = pr_sub.add_parser("show", help="Show a preset as JSON")
    p_pr_show.add_argument("preset_id", metavar="ID")
    p_pr_show.set_defaults(func=cmd_presets)

    p_pr_save = pr_sub.add_parser("save", help="Save a new preset")
    p_pr_save.add_argument("preset_id", metavar="ID")
    p_pr_save.add_argument("--name", help="Display name")
    p_pr_save.add_argument("--description", default="", help="Description")
    p_pr_save.add_argument(
        "--steps",
        nargs="+",
        metavar="STEP",
        help="Inline steps: arena:5 farm:forever",
    )
    p_pr_save.add_argument("--from-file", metavar="JSON", help="Load steps from JSON file")
    p_pr_save.add_argument("--overwrite", action="store_true", help="Replace existing preset")
    p_pr_save.add_argument("--no-recover", action="store_true", help="No automatic recovery")
    p_pr_save.set_defaults(func=cmd_presets)

    p_pr_del = pr_sub.add_parser("delete", help="Delete a preset")
    p_pr_del.add_argument("preset_id", metavar="ID")
    p_pr_del.set_defaults(func=cmd_presets)

    return parser


def cmd_test(args: argparse.Namespace) -> None:
    from .testing.fixtures import list_fixtures, save_fixture

    if args.action == "list":
        items = list_fixtures()
        if not items:
            print("No fixtures in tests/fixtures/screens/")
            return
        print("Fixtures:")
        for item in items:
            print(f"  {item}")
        return

    if args.action == "capture":
        if not args.name:
            log.error("Usage: python -m bot.cli test capture arena/opponents_popup")
            sys.exit(2)
        device = _connect()
        img = device.screenshot()
        path = save_fixture(img, *args.name.split("/"))
        print(f"Saved: {path}")
        return

    if args.action == "vision":
        from . import vision

        name = args.name or "arena/opponents_popup"
        from .testing.fixtures import load_fixture

        try:
            screen = load_fixture(*name.split("/"))
        except FileNotFoundError:
            log.error("Fixture not found: %s", name)
            sys.exit(2)
        print(f"Fixture: {name}")
        print(f"  arena popup: {vision.is_arena_opponents_popup(screen)}")
        rows = vision.find_arena_power_row_ys(screen)
        print(f"  opponent rows: {rows}")
        for i in range(min(5, len(rows))):
            power = vision.read_arena_opponent_power(screen, i)
            print(f"  opponent #{i + 1} power: {power if power is not None else '?'}M")
        return

    if args.action == "flows":
        from .testing.flows import COMBAT_FLOWS

        print("Registered combat flows:")
        for spec in COMBAT_FLOWS:
            claim = spec.claim or "(play/farm)"
            print(f"  {spec.flow_id}: {spec.label} -> daily {claim}")
        print("\nMock: python -m bot.cli test flow arena")
        print("Live: python -m bot.cli test flow arena --live")
        return

    if args.action == "flow":
        from .testing.flows import COMBAT_FLOWS, flow_by_id, run_live_flow, run_mock_flow

        flow_id = args.name
        if not flow_id:
            print("Flows:", ", ".join(f.flow_id for f in COMBAT_FLOWS))
            sys.exit(2)
        if flow_by_id(flow_id) is None:
            log.error("Unknown flow: %s", flow_id)
            sys.exit(2)
        if args.live:
            device = _connect()
            ctx = BotContext(device)
            result = run_live_flow(flow_id, ctx)
        else:
            from .testing.fixtures import load_fixture

            lobby = None
            battle = None
            try:
                lobby = load_fixture(flow_id, "lobby.png")
            except FileNotFoundError:
                pass
            try:
                battle = load_fixture(flow_id, "battle.png")
            except FileNotFoundError:
                pass
            result = run_mock_flow(flow_id, lobby_factory=lambda: lobby, battle_factory=lambda: battle)
        status = "OK" if result.ok else "FAIL"
        print(f"[{status}] flow={result.flow_id} combat={result.entered_combat} lobby={result.returned_lobby}")
        if result.error:
            print(f"  error: {result.error}")
        if not result.ok:
            sys.exit(1)
        return

    log.error("Unknown action: %s", args.action)
    sys.exit(2)


def cmd_panel(args: argparse.Namespace) -> None:
    from .panel.server import run_panel

    run_panel(host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    clear_stop_file()
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except StopRequested as exc:
        log.warning("Stopped: %s", exc)
    except KeyboardInterrupt:
        log.warning("Interrupted by user (Ctrl+C)")


if __name__ == "__main__":
    main()
