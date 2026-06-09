"""Navegación consciente de pantalla: volver al lobby de campaña antes de tareas."""
from __future__ import annotations

import time

from .device import sleep
from .log import get_logger
from .paths.base import BotContext
from .screens import ScreenId, is_lobby

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


def log_screen(ctx: BotContext, prefix: str = "") -> ScreenId:
    sid = ctx.current_screen()
    msg = f"Pantalla actual: {sid.value}"
    if prefix:
        msg = f"{prefix} — {msg}"
    log.info(msg)
    return sid


def ensure_campaign_lobby(ctx: BotContext, *, exit_combat: bool = False) -> bool:
    """Vuelve al lobby de campaña (mapa principal). No interrumpe combate activo salvo exit_combat."""
    from .run_end_dismiss import dismiss_to_lobby, needs_post_run_dismiss

    sid = log_screen(ctx, "Navegación")

    if is_lobby(ctx.device.screenshot()):
        return True

    screen = ctx.device.screenshot()
    if needs_post_run_dismiss(screen):
        log.info("Post-run detectado antes de navegar -> cerrar recompensas")
        if dismiss_to_lobby(ctx):
            return True

    sid = ctx.current_screen()

    if is_combat_active(sid):
        screen = ctx.device.screenshot()
        if needs_post_run_dismiss(screen):
            log.info("Post-run sobre pantalla %s -> tap cerrar (no exit combat)", sid.value)
            return dismiss_to_lobby(ctx)
        if not exit_combat or getattr(ctx, "hold_combat", False):
            if getattr(ctx, "hold_combat", False):
                log.info("Run en progreso (hold_combat); no navego")
            else:
                log.warning("En combate activo (%s); no navego al lobby", sid.value)
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
            log.info("Lobby de campaña alcanzado")
            return True
        sid = ctx.current_screen()
        if is_combat_active(sid) and exit_combat:
            screen = ctx.device.screenshot()
            if needs_post_run_dismiss(screen):
                log.info("Post-run en loop nav (%s) -> dismiss", sid.value)
                dismiss_to_lobby(ctx, max_rounds=2)
                sleep(1.0)
                continue
            _exit_combat(ctx)
            sleep(1.0)
            continue
        if sid in COMBAT_END:
            _dismiss_run_end(ctx)
            continue
        _close_overlays(ctx, attempt)

    ok = is_lobby(ctx.device.screenshot())
    if not ok:
        log.warning("No se confirmó lobby tras navegación (quedó en %s)", ctx.current_screen().value)
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
    """Garantiza juego abierto y lobby visible antes de iniciar un bot."""
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
            log.info("Run activa detectada (%s); listo para reanudar", sid.value)
            return True
        return False

    def launch_and_wait(reason: str) -> bool:
        log.warning("%s; abro el juego", reason)
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
                log.info("Juego abrió en run activa (%s); reanudo", sid.value)
                return True
            if sid != ScreenId.UNKNOWN:
                break
            sleep(2.0)
        return False

    nav_exit_combat = exit_combat and not allow_combat

    if current_ready():
        return True

    if launch_game:
        try:
            screen = ctx.device.screenshot()
            if is_lobby(screen):
                return True
            if ctx.current_screen() == ScreenId.UNKNOWN and launch_and_wait("Pantalla inicial unknown"):
                return True
        except RuntimeError:
            if launch_and_wait("No pude capturar pantalla inicial"):
                return True

    if ensure_campaign_lobby(ctx, exit_combat=nav_exit_combat):
        return True
    if current_ready():
        return True
    if not launch_game:
        return False

    for attempt in range(max(1, max_launch_attempts)):
        if launch_and_wait(f"No se confirmó lobby (intento {attempt + 1}/{max_launch_attempts})"):
            return True
        if ensure_campaign_lobby(ctx, exit_combat=nav_exit_combat):
            return True
        if current_ready():
            return True
    return False


def prepare_for_task(ctx: BotContext, task: str) -> None:
    """Prepara el emulador antes de una tarea del panel/CLI."""
    sid = log_screen(ctx, f"Tarea {task}")

    combat_tasks = {"farm", "farm_forever", "play"}

    if task in combat_tasks:
        from .run_end_dismiss import configure_farm_ctx, dismiss_to_lobby, needs_post_run_dismiss

        if task in ("farm", "farm_forever"):
            configure_farm_ctx(ctx)

        screen = ctx.device.screenshot()
        if needs_post_run_dismiss(screen):
            log.info("Farm/play: post-run detectado -> cerrar recompensas")
            if not dismiss_to_lobby(ctx):
                raise NavigationError("No se pudo cerrar pantalla post-run antes del farm")
            return
        sid = ctx.current_screen()
        if is_combat_active(sid):
            screen = ctx.device.screenshot()
            if needs_post_run_dismiss(screen):
                log.info("Farm/play: post-run sobre %s -> cerrar recompensas", sid.value)
                if not dismiss_to_lobby(ctx):
                    raise NavigationError("No se pudo cerrar pantalla post-run antes del farm")
                return
            log.info("Farm/play: ya en combate (%s); reanudo run activa", sid.value)
            return
        if not ensure_game_lobby(ctx, exit_combat=True, allow_combat=True):
            raise NavigationError("No se pudo abrir el juego y llegar al lobby/run activa para iniciar farm/play")
        return

    if task == "skills_scan":
        if sid == ScreenId.SKILL_SELECT:
            return
        if is_combat_active(sid):
            raise NavigationError("En combate; poné skill select o esperá al fin del run")
        if not ensure_game_lobby(ctx, exit_combat=True):
            raise NavigationError("Abrí el juego en skill select o lobby de campaña")
        raise NavigationError("No estás en skill select; entrá a un level-up primero")

    if is_combat_active(sid):
        raise NavigationError(
            f"En combate ({sid.value}); no inicio '{task}'. Usá STOP o esperá a que termine el run."
        )

    if not ensure_game_lobby(ctx, exit_combat=True):
        raise NavigationError(f"No se pudo abrir el juego y llegar al lobby para '{task}'")


def _exit_combat(ctx: BotContext) -> None:
    from . import vision

    log.info("Saliendo de combate activo...")
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
        log.warning("No pude salir de combate: %s", exc)


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
