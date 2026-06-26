"""Screen-aware navigation: return to campaign lobby before tasks."""
from __future__ import annotations

import time

from .device import sleep
from .log import get_logger
from .paths.base import BotContext
from .screens import ScreenId, identify, identify_arena, is_lobby

log = get_logger("nav")

COMBAT_ACTIVE = frozenset({
    ScreenId.BATTLE,
    ScreenId.SKILL_SELECT,
    ScreenId.ROULETTE,
    ScreenId.DEVIL_DEAL,
})

COMBAT_END = frozenset({ScreenId.VICTORY, ScreenId.DEFEAT})


class NavigationError(Exception):
    pass


def is_combat_active(sid: ScreenId) -> bool:
    return sid in COMBAT_ACTIVE


def _game_is_open(ctx: BotContext) -> bool:
    try:
        screen = ctx.device.screenshot()
    except RuntimeError:
        return False
    if identify(screen) != ScreenId.UNKNOWN:
        return True
    if identify_arena(screen) is not None:
        return True
    return False


def log_screen(ctx: BotContext, prefix: str = "") -> ScreenId:
    sid = ctx.current_screen()
    msg = f"Current screen: {sid.value}"
    if prefix:
        msg = f"{prefix} — {msg}"
    log.info(msg)
    return sid


def _close_arena_if_needed(ctx: BotContext) -> bool:
    sid = identify_arena(ctx.device.screenshot())
    if sid == ScreenId.ARENA_PERSONAL_INFO:
        log.info("Nav: closing Arena Personal Info")
        ctx.back(settle=0.5)
        return True
    if sid == ScreenId.ARENA_OPPONENTS:
        log.info("Nav: closing Challenge popup (back)")
        ctx.back(settle=0.5)
        return True
    if sid == ScreenId.ARENA_LEADERBOARD:
        log.info("Nav: leaving Arena leaderboard")
        ctx.back(settle=0.4)
        sleep(0.3)
        try:
            ctx.tap_point("nav", "campaign", money_check=False, settle=0.8)
        except ValueError:
            pass
        return True
    return False


def ensure_campaign_lobby(ctx: BotContext, *, exit_combat: bool = False) -> bool:
    """Return to campaign lobby (main map). Does not interrupt active combat unless exit_combat."""
    from .run_end_dismiss import dismiss_to_lobby, needs_post_run_dismiss

    sid = log_screen(ctx, "Navigation")

    if is_lobby(ctx.device.screenshot()):
        return True

    screen = ctx.device.screenshot()
    if needs_post_run_dismiss(screen):
        log.info("Post-run detected before navigation -> close rewards")
        if dismiss_to_lobby(ctx):
            return True

    sid = ctx.current_screen()

    if is_combat_active(sid):
        screen = ctx.device.screenshot()
        if needs_post_run_dismiss(screen):
            log.info("Post-run on screen %s -> tap close (no exit combat)", sid.value)
            return dismiss_to_lobby(ctx)
        if not exit_combat or getattr(ctx, "hold_combat", False):
            if getattr(ctx, "hold_combat", False):
                log.info("Run in progress (hold_combat); not navigating")
            else:
                log.warning("In active combat (%s); not navigating to lobby", sid.value)
            return False
        _exit_combat(ctx)
        sleep(1.0)
        if is_lobby(ctx.device.screenshot()):
            return True

    if sid in COMBAT_END:
        _dismiss_run_end(ctx)

    for attempt in range(6):
        ctx.kill.check()
        if is_lobby(ctx.device.screenshot()):
            log.info("Campaign lobby reached")
            return True
        sid = ctx.current_screen()
        if is_combat_active(sid) and exit_combat:
            screen = ctx.device.screenshot()
            if needs_post_run_dismiss(screen):
                log.info("Post-run in nav loop (%s) -> dismiss", sid.value)
                dismiss_to_lobby(ctx, max_rounds=2)
                sleep(1.0)
                continue
            _exit_combat(ctx)
            sleep(1.0)
            continue
        if sid in COMBAT_END:
            _dismiss_run_end(ctx)
            continue
        if _close_arena_if_needed(ctx):
            sleep(0.5)
            continue
        _close_overlays(ctx, attempt)

    ok = is_lobby(ctx.device.screenshot())
    if not ok:
        log.warning("Lobby not confirmed after navigation (stuck on %s)", ctx.current_screen().value)
    return ok


def ensure_game_lobby(
    ctx: BotContext,
    *,
    exit_combat: bool = True,
    launch_game: bool = True,
    launch_wait_s: float = 8.0,
    game_visible_timeout: float = 60.0,
    max_launch_attempts: int = 2,
    allow_combat: bool = False,
) -> bool:
    """Ensure game is open and lobby is visible before starting a bot."""
    from .emulator import EmulatorConsole

    def current_ready() -> bool:
        try:
            screen = ctx.device.screenshot()
        except RuntimeError:
            return False
        if is_lobby(screen):
            return True
        sid = ctx.current_screen()
        if allow_combat and is_combat_active(sid):
            log.info("Active run detected (%s); ready to resume", sid.value)
            return True
        return False

    def launch_and_wait(reason: str) -> bool:
        if _game_is_open(ctx):
            sid = ctx.current_screen()
            log.info(
                "Game already visible (%s); not relaunching app (%s)",
                sid.value,
                reason,
            )
            if ensure_campaign_lobby(ctx, exit_combat=nav_exit_combat):
                return True
            return current_ready()
        log.warning("%s; launching game", reason)
        EmulatorConsole().run_app()
        sleep(launch_wait_s)
        deadline = time.time() + game_visible_timeout
        while time.time() < deadline:
            ctx.kill.check()
            try:
                screen = ctx.device.screenshot()
            except RuntimeError:
                sleep(2.0)
                continue
            if is_lobby(screen):
                return True
            sid = ctx.current_screen()
            if allow_combat and is_combat_active(sid):
                log.info("Game opened in active run (%s); resuming", sid.value)
                return True
            if _game_is_open(ctx):
                log.info("Game visible after launch (%s)", sid.value)
                return True
            sleep(2.0)
        return False

    nav_exit_combat = exit_combat and not allow_combat

    if current_ready():
        return True

    if launch_game and _game_is_open(ctx):
        if ensure_campaign_lobby(ctx, exit_combat=nav_exit_combat):
            return True
        if current_ready():
            return True

    if launch_game:
        try:
            screen = ctx.device.screenshot()
            if is_lobby(screen):
                return True
            if _game_is_open(ctx):
                pass
            elif ctx.current_screen() == ScreenId.UNKNOWN and launch_and_wait(
                "Initial screen unknown"
            ):
                return True
        except RuntimeError:
            if launch_and_wait("Could not capture initial screen"):
                return True

    if ensure_campaign_lobby(ctx, exit_combat=nav_exit_combat):
        return True
    if current_ready():
        return True
    if not launch_game:
        return False

    if _game_is_open(ctx):
        log.warning(
            "Game open (%s) but lobby not confirmed; not relaunching MuMu",
            ctx.current_screen().value,
        )
        return False

    for attempt in range(max(1, max_launch_attempts)):
        if launch_and_wait(f"Lobby not confirmed (attempt {attempt + 1}/{max_launch_attempts})"):
            return True
        if ensure_campaign_lobby(ctx, exit_combat=nav_exit_combat):
            return True
        if current_ready():
            return True
    return False


def prepare_for_task(ctx: BotContext, task: str) -> None:
    """Prepare the emulator before a panel/CLI task."""
    sid = log_screen(ctx, f"Task {task}")

    combat_tasks = {"farm", "farm_forever", "play"}

    if task in combat_tasks:
        from .run_end_dismiss import configure_farm_ctx, dismiss_to_lobby, needs_post_run_dismiss

        if task in ("farm", "farm_forever"):
            configure_farm_ctx(ctx)

        screen = ctx.device.screenshot()
        if needs_post_run_dismiss(screen):
            log.info("Farm/play: post-run detected -> close rewards")
            if not dismiss_to_lobby(ctx):
                raise NavigationError("Could not close post-run screen before farm")
            return
        sid = ctx.current_screen()
        if is_combat_active(sid):
            screen = ctx.device.screenshot()
            if needs_post_run_dismiss(screen):
                log.info("Farm/play: post-run on %s -> close rewards", sid.value)
                if not dismiss_to_lobby(ctx):
                    raise NavigationError("Could not close post-run screen before farm")
                return
            log.info("Farm/play: already in combat (%s); resuming active run", sid.value)
            return
        if not ensure_game_lobby(ctx, exit_combat=True, allow_combat=True):
            raise NavigationError("Could not open game and reach lobby/active run to start farm/play")
        return

    if task == "skills_scan":
        if sid == ScreenId.SKILL_SELECT:
            return
        if is_combat_active(sid):
            raise NavigationError("In combat; open skill select or wait for the run to end")
        if not ensure_game_lobby(ctx, exit_combat=True):
            raise NavigationError("Open the game on skill select or campaign lobby")
        raise NavigationError("Not on skill select; enter a level-up first")

    if is_combat_active(sid):
        raise NavigationError(
            f"In combat ({sid.value}); not starting '{task}'. Use STOP or wait for the run to end."
        )

    if not ensure_game_lobby(ctx, exit_combat=True):
        raise NavigationError(f"Could not open game and reach lobby for '{task}'")


def _exit_combat(ctx: BotContext) -> None:
    from . import vision

    log.info("Exiting active combat...")
    try:
        ctx.tap_point("battle", "pause", money_check=False, settle=0.8)
        ctx.tap_point("battle", "exit_battle", money_check=False, settle=0.6)
        sleep(0.5)
        try:
            match = vision.find_template(ctx.device.screenshot(), "anchors/confirm_btn.png")
            if match.confidence >= 0.75:
                ctx.tap(match.cx, match.cy, money_check=False, settle=1.0)
                return
        except FileNotFoundError:
            pass
        ctx.tap_point("battle", "exit_confirm", money_check=False, settle=0.8)
    except ValueError as exc:
        log.warning("Could not exit combat: %s", exc)


def _dismiss_run_end(ctx: BotContext) -> None:
    from .run_end_dismiss import dismiss_to_lobby

    dismiss_to_lobby(ctx, max_rounds=3)


def _close_overlays(ctx: BotContext, attempt: int) -> None:
    from .run_end_dismiss import dismiss_to_lobby, needs_post_run_dismiss

    screen = ctx.device.screenshot()
    if needs_post_run_dismiss(screen):
        dismiss_to_lobby(ctx, max_rounds=2)
        return
    ctx.back(settle=0.8)
