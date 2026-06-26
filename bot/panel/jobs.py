"""Runnable tasks from the panel (same logic as the CLI)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from ..device import Device
from ..failsafes import StopRequested, clear_stop_file
from ..log import get_logger
from ..paths.base import BotContext
from ..paths.daily import DailyPath, MAIN_LOOP_ORDER
from ..paths.play_level import PlayLevelPath

log = get_logger("panel")


class JobBusyError(Exception):
    pass


class JobConnectionError(Exception):
    pass


def connect_device() -> Device:
    from ..recovery import reconnect_adb

    device = Device()
    if not reconnect_adb(device):
        raise JobConnectionError(
            f"ADB not connected to {device.serial}. Open the emulator or run emulator reconnect."
        )
    log.info("Panel: connected to %s", device.serial)
    return device


@dataclass
class JobRunner:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    label: str = ""
    last_error: str | None = None
    _thread: threading.Thread | None = None

    def start(self, label: str, fn: Callable[[], None]) -> None:
        with self._lock:
            if self.running:
                raise JobBusyError(f"Already running: {self.label}")
            clear_stop_file()
            self.running = True
            self.label = label
            self.last_error = None

            def _wrap() -> None:
                from ..navigation import NavigationError

                try:
                    fn()
                except StopRequested as exc:
                    log.warning("Panel stopped: %s", exc)
                except JobConnectionError as exc:
                    self.last_error = str(exc)
                    log.error("%s", exc)
                except NavigationError as exc:
                    self.last_error = str(exc)
                    log.error("%s", exc)
                except Exception as exc:  # noqa: BLE001
                    self.last_error = str(exc)
                    log.exception("Panel job failed (%s): %s", label, exc)
                finally:
                    with self._lock:
                        self.running = False
                        self.label = ""

            self._thread = threading.Thread(target=_wrap, name=f"panel-{label}", daemon=True)
            self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "label": self.label,
                "last_error": self.last_error,
            }


RUNNER = JobRunner()


def run_emulator_launch() -> None:
    from ..emulator import EmulatorConsole

    EmulatorConsole().launch()


def run_emulator_open_game() -> None:
    from ..emulator import EmulatorConsole

    console = EmulatorConsole()
    if not console.is_running():
        console.launch()
    console.run_app()


def run_emulator_reconnect() -> None:
    from ..recovery import reconnect_adb

    device = Device()
    if not reconnect_adb(device):
        raise JobConnectionError(f"Could not reconnect ADB to {device.serial}")


def run_emulator_reboot() -> None:
    from ..recovery import reboot_emulator_and_wait_lobby

    device = Device()
    if not reboot_emulator_and_wait_lobby(device):
        raise RuntimeError("Emulator reboot did not complete (ADB or lobby)")


run_ldplayer_launch = run_emulator_launch
run_ldplayer_open_game = run_emulator_open_game
run_ldplayer_reconnect = run_emulator_reconnect
run_ldplayer_reboot = run_emulator_reboot


def run_calibrate_identify() -> None:
    from .. import screens

    device = connect_device()
    sid = screens.identify(device.screenshot())
    log.info("Current screen: %s", sid.value)


def run_calibrate_shot() -> None:
    import time

    device = connect_device()
    name = time.strftime("panel_%Y%m%d_%H%M%S.png")
    device.screenshot(save_as=name)
    log.info("Screenshot saved: screenshots/%s", name)


def run_calibrate_read_floor() -> None:
    from .. import vision
    from ..configs import Coords

    device = connect_device()
    try:
        region = Coords.load().region("lobby", "campaign_floor_badge")
    except (KeyError, ValueError):
        region = vision.DEFAULT_CAMPAIGN_FLOOR_BADGE
    floor = vision.read_campaign_floor_badge(device.screenshot(), region)
    log.info("Floor read: %s", floor if floor is not None else "(unreadable)")


def run_skills_scan() -> None:
    from .. import screens
    from ..configs import Coords
    from ..navigation import prepare_for_task
    from ..screens import ScreenId
    from ..skills import SkillPicker

    device = connect_device()
    ctx = BotContext(device)
    prepare_for_task(ctx, "skills_scan")
    screen = device.screenshot()
    sid = screens.identify(screen)
    if sid != ScreenId.SKILL_SELECT:
        log.warning("Current screen: %s (expected skill_select)", sid.value)
    picker = SkillPicker()
    try:
        fallback = Coords.load().regions("skill_select", "cards")
    except (KeyError, ValueError):
        fallback = None
    regions = picker.detect_cards(screen)
    if len(regions) < 2 and fallback:
        regions = fallback
    evaluations = picker.evaluate(screen, regions, catalog=True)
    if not evaluations:
        log.warning("Skills scan: no cards detected")
        return
    log.info("Cataloged %d visible cards (all, not just the chosen one)", len(evaluations))
    if picker.selection_mode == "score":
        ranked = sorted(evaluations, key=lambda e: (-e.score, -e.confidence))
    else:
        ranked = sorted(evaluations, key=lambda e: (picker._rank(e.category), -e.confidence))
    for i, ev in enumerate(ranked, 1):
        mark = " <- would pick" if i == 1 else ""
        log.info(
            "Skills scan %d: card %d %s score=%d conf=%.2f%s",
            i,
            ev.index,
            ev.skill_id,
            ev.score,
            ev.confidence,
            mark,
        )


def run_skills_list() -> None:
    from ..skill_scores import format_skill_table, list_skill_rows

    text = format_skill_table(list_skill_rows())
    for line in text.splitlines():
        log.info("[skills] %s", line)


def run_pipeline(
    steps: list[dict[str, Any]],
    *,
    name: str = "panel",
    recover_on_failure: bool = True,
    resume: bool = False,
) -> None:
    from ..pipeline import (
        PipelineRunner,
        build_state_from_steps,
        load_state,
    )

    device = connect_device()
    ctx = BotContext(device)
    runner = PipelineRunner(ctx)

    if resume:
        state = load_state()
        if state is None:
            raise RuntimeError("No pending run to resume")
        runner.run(state, resume=True)
        return

    if not steps:
        raise ValueError("Chain is empty; enable at least one step")
    state = build_state_from_steps(steps, name=name, recover_on_failure=recover_on_failure)
    runner.run(state, resume=False)


def dispatch(job: str, params: dict[str, Any]) -> None:
    force = bool(params.get("force"))
    recover = bool(params.get("recover_emulator", params.get("recover_ldplayer")))

    if job.startswith("daily:"):
        claim = job.split(":", 1)[1]
        RUNNER.start(
            job,
            lambda: _run_daily_prepared(
                [claim],
                force=True,
                recover_emulator=recover,
                task_id=job,
            ),
        )
        return

    if job == "pipeline":
        chain = params.get("chain") or []
        from .catalog import chain_to_steps

        steps = chain_to_steps(chain) if chain and "action" not in (chain[0] if chain else {}) else chain
        label = str(params.get("name") or "pipeline")
        RUNNER.start(
            label,
            lambda: run_pipeline(
                steps,
                name=label,
                recover_on_failure=bool(params.get("recover_on_failure", True)),
                resume=bool(params.get("resume")),
            ),
        )
        return

    if job == "pipeline_resume":
        RUNNER.start(
            "resume",
            lambda: run_pipeline([], name="resume", resume=True),
        )
        return

    starters: dict[str, Callable[[], None]] = {
        "farm": lambda: RUNNER.start("farm", lambda: _run_farm_prepared(forever=False)),
        "farm_forever": lambda: RUNNER.start("farm_forever", lambda: _run_farm_prepared(forever=True)),
        "play": lambda: RUNNER.start(
            "play", lambda: _run_play_prepared(games=int(params.get("games", 5)))
        ),
        "daily_main": lambda: RUNNER.start(
            "daily_main",
            lambda: _run_daily_prepared(list(MAIN_LOOP_ORDER), force=force, recover_emulator=recover),
        ),
        "emulator_launch": lambda: RUNNER.start("emulator_launch", run_emulator_launch),
        "emulator_open_game": lambda: RUNNER.start("emulator_open_game", run_emulator_open_game),
        "emulator_reconnect": lambda: RUNNER.start("emulator_reconnect", run_emulator_reconnect),
        "emulator_reboot": lambda: RUNNER.start("emulator_reboot", run_emulator_reboot),
        "ldplayer_launch": lambda: RUNNER.start("ldplayer_launch", run_emulator_launch),
        "ldplayer_open_game": lambda: RUNNER.start("ldplayer_open_game", run_emulator_open_game),
        "ldplayer_reconnect": lambda: RUNNER.start("ldplayer_reconnect", run_emulator_reconnect),
        "ldplayer_reboot": lambda: RUNNER.start("ldplayer_reboot", run_emulator_reboot),
        "calibrate_identify": lambda: RUNNER.start("calibrate_identify", run_calibrate_identify),
        "calibrate_shot": lambda: RUNNER.start("calibrate_shot", run_calibrate_shot),
        "calibrate_read_floor": lambda: RUNNER.start("calibrate_read_floor", run_calibrate_read_floor),
        "skills_scan": lambda: RUNNER.start("skills_scan", run_skills_scan),
        "skills_list": lambda: RUNNER.start("skills_list", run_skills_list),
    }

    starter = starters.get(job)
    if starter is None:
        raise ValueError(f"Unknown job: {job}")
    starter()


def _run_farm_prepared(*, forever: bool) -> None:
    from ..navigation import prepare_for_task
    from ..run_end_dismiss import configure_farm_ctx

    device = connect_device()
    ctx = BotContext(device)
    configure_farm_ctx(ctx)
    prepare_for_task(ctx, "farm_forever" if forever else "farm")
    PlayLevelPath(
        ctx,
        level=50,
        games=None,
        battle_timeout=600.0,
        max_games=40,
        forever=forever,
        energy_wait_s=60.0 * 60.0,
        dodge=False,
    ).run()


def _run_play_prepared(*, games: int) -> None:
    from ..navigation import prepare_for_task

    device = connect_device()
    ctx = BotContext(device)
    prepare_for_task(ctx, "play")
    PlayLevelPath(ctx, level=50, games=games, battle_timeout=600.0, dodge=False).run()


def _run_daily_prepared(
    claims: list[str] | None,
    *,
    force: bool,
    recover_emulator: bool,
    task_id: str = "daily_main",
) -> None:
    from ..navigation import prepare_for_task

    device = connect_device()
    ctx = BotContext(device)
    prepare_for_task(ctx, task_id)
    DailyPath(ctx, force=force, recover_emulator=recover_emulator).run(claims)
