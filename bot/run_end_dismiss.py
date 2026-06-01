"""Cierre de pantallas post-run (recompensas, runas, popups de detalle)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import vision
from .device import sleep
from .log import dump_screen, get_logger
from .screens import ScreenId, identify, is_lobby

if TYPE_CHECKING:
    from .paths.base import BotContext

log = get_logger("run_end")

POST_RUN_TAP = (450, 1552)
FARM_POST_RUN_TAP = (100, 1555)
CHALLENGE_END_PIXEL = (450, 330)
CHALLENGE_ENDED_ANCHOR = "anchors/challenge_ended.png"
BANNER_SEARCH_REGION = (80, 240, 740, 160)
BANNER_TEMPLATE_THRESHOLD = 0.70
BANNER_TITLE_Y = (305, 355)
BANNER_TITLE_X = (250, 650)


def configure_farm_ctx(ctx: BotContext) -> None:
    ctx.post_run_tap = FARM_POST_RUN_TAP


def _resolve_post_run_tap(ctx: BotContext) -> tuple[int, int, str]:
    custom = getattr(ctx, "post_run_tap", None)
    if custom:
        return int(custom[0]), int(custom[1]), "farm"
    return POST_RUN_TAP[0], POST_RUN_TAP[1], "default"


def post_run_dismiss_tap(_screen=None) -> tuple[int, int]:
    return POST_RUN_TAP


def find_safe_post_run_tap(_screen=None) -> tuple[int, int, str]:
    return POST_RUN_TAP[0], POST_RUN_TAP[1], "calibrated"


def _loot_grid_heuristic(screen) -> bool:
    h, w = screen.shape[:2]
    center = screen[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
    if center.size == 0:
        return False
    mean = float(center.mean())
    std = float(center.std())
    return mean < 70.0 and std > 40.0


def _banner_pixel_match_strict(screen, x: int, y: int) -> bool:
    try:
        b, g, r = screen[y, x]
    except IndexError:
        return False
    ri, gi, bi = int(r), int(g), int(b)
    return bi > 165 and 95 <= gi <= 110 and 45 <= ri <= 60


def _roulette_on_field(screen) -> bool:
    try:
        return vision.matches(screen, "anchors/roulette.png", threshold=0.68)
    except FileNotFoundError:
        return False


def _center_banner_teal_count(screen) -> int:
    y0, y1 = BANNER_TITLE_Y
    x0, x1 = BANNER_TITLE_X
    hits = 0
    for y in range(y0, y1, 5):
        for x in range(x0, x1, 12):
            if _banner_pixel_match_strict(screen, x, y):
                hits += 1
    return hits


def _center_banner_text_count(screen) -> int:
    y0, y1 = BANNER_TITLE_Y
    x0, x1 = BANNER_TITLE_X
    hits = 0
    for y in range(y0, y1, 5):
        for x in range(x0, x1, 8):
            try:
                b, g, r = screen[y, x]
            except IndexError:
                continue
            ri, gi, bi = int(r), int(g), int(b)
            if ri > 190 and gi > 190 and bi > 190:
                hits += 1
    return hits


def _challenge_ended_template(screen) -> bool:
    try:
        return vision.matches(
            screen,
            CHALLENGE_ENDED_ANCHOR,
            threshold=BANNER_TEMPLATE_THRESHOLD,
            region=BANNER_SEARCH_REGION,
        )
    except FileNotFoundError:
        return False


def _center_banner_ribbon(screen) -> bool:
    return _center_banner_teal_count(screen) >= 3 and _center_banner_text_count(screen) >= 14


def is_challenge_ended_screen(screen) -> bool:
    if _roulette_on_field(screen):
        return False
    if _challenge_ended_template(screen):
        return True
    if _banner_pixel_match_strict(screen, CHALLENGE_END_PIXEL[0], CHALLENGE_END_PIXEL[1]):
        return True
    return _center_banner_ribbon(screen)


def is_challenge_ended_banner(screen) -> bool:
    return is_challenge_ended_screen(screen)


def _beige_item_card_heuristic(screen) -> bool:
    h, w = screen.shape[:2]
    card = screen[h // 6 : 5 * h // 6, w // 8 : 7 * w // 8]
    if card.size == 0:
        return False
    mean = float(card.mean())
    std = float(card.std())
    if mean < 100.0 or std > 50.0:
        return False
    x_btn = screen[130:240, 680:820]
    if x_btn.size == 0 or float(x_btn.std()) < 30.0:
        return False
    hint = screen[max(0, h - 140) : h - 20, max(0, w // 2 - 200) : min(w, w // 2 + 200)]
    return hint.size > 0 and float(hint.mean()) > 12.0


def is_item_detail_popup(screen) -> bool:
    if is_lobby(screen) or _roulette_on_field(screen):
        return False
    if not _beige_item_card_heuristic(screen):
        return False
    return is_challenge_ended_screen(screen) or _loot_grid_heuristic(screen)


def is_post_run_rewards(screen) -> bool:
    if is_lobby(screen):
        return False
    if is_challenge_ended_screen(screen):
        return True
    sid = identify(screen)
    return sid in (ScreenId.VICTORY, ScreenId.DEFEAT)


_COMBAT_SCREENS = frozenset(
    {
        ScreenId.BATTLE,
        ScreenId.SKILL_SELECT,
        ScreenId.ROULETTE,
        ScreenId.DEVIL_DEAL,
    }
)


def is_post_run_overlay(screen) -> bool:
    if is_lobby(screen):
        return False
    sid = identify(screen)
    if sid in (ScreenId.VICTORY, ScreenId.DEFEAT):
        return True
    if sid in (ScreenId.SKILL_SELECT, ScreenId.ROULETTE, ScreenId.DEVIL_DEAL, ScreenId.LEVEL_SELECT):
        return False
    if _roulette_on_field(screen):
        return False
    if is_challenge_ended_screen(screen):
        return True
    if is_item_detail_popup(screen):
        return True
    return False


def needs_post_run_dismiss(screen) -> bool:
    """True solo para recompensas post-run reales (no combate activo)."""
    if is_lobby(screen):
        return False
    sid = identify(screen)
    if sid in (ScreenId.VICTORY, ScreenId.DEFEAT):
        return True
    if sid in (ScreenId.SKILL_SELECT, ScreenId.ROULETTE, ScreenId.DEVIL_DEAL):
        return False
    if _roulette_on_field(screen):
        return False
    return is_challenge_ended_screen(screen)


def is_post_run_context(screen) -> bool:
    return needs_post_run_dismiss(screen) or is_item_detail_popup(screen)


def is_confirmed_challenge_ended(screen, confirm_screen) -> bool:
    return is_challenge_ended_screen(screen) and is_challenge_ended_screen(confirm_screen)


def _post_run_tap_sequence(ctx: BotContext) -> list[tuple[int, int, str]]:
    taps: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()

    def add(x: int, y: int, src: str) -> None:
        key = (x, y)
        if key not in seen:
            seen.add(key)
            taps.append((x, y, src))

    custom = getattr(ctx, "post_run_tap", None)
    if custom:
        add(int(custom[0]), int(custom[1]), "farm")
    add(POST_RUN_TAP[0], POST_RUN_TAP[1], "default")
    try:
        p = ctx.coords.point("run_end", "continue")
        add(p.x, p.y, "coords")
    except (KeyError, ValueError):
        pass
    try:
        p = ctx.coords.point("run_end", "continue_farm")
        add(p.x, p.y, "coords_farm")
    except (KeyError, ValueError):
        pass
    return taps


def _tap_dismiss(ctx: BotContext, x: int, y: int, src: str) -> None:
    log.info("tap post-run (%d,%d) src=%s", x, y, src)
    ctx.tap(x, y, money_check=False, settle=0.0)
    sleep(1.8)


def dismiss_post_run_overlays(ctx: BotContext, *, tap: tuple[int, int, str] | None = None) -> None:
    screen = ctx.device.screenshot()
    if is_lobby(screen):
        return
    if is_item_detail_popup(screen):
        log.info("post-run: popup ítem -> back")
        ctx.back(settle=0.6)
        if is_lobby(ctx.device.screenshot()):
            return
    if tap is None:
        x, y, src = _resolve_post_run_tap(ctx)
    else:
        x, y, src = tap
    _tap_dismiss(ctx, x, y, src)


def dismiss_to_lobby(ctx: BotContext, *, max_rounds: int = 4) -> bool:
    taps = _post_run_tap_sequence(ctx)
    if not taps:
        taps = [(POST_RUN_TAP[0], POST_RUN_TAP[1], "default")]
    log.info(
        "post-run dismiss inicio taps=%s",
        ", ".join(f"({x},{y},{s})" for x, y, s in taps),
    )

    for round_i in range(max_rounds):
        screen = ctx.device.screenshot()
        if is_lobby(screen):
            log.info("post-run: lobby OK (ronda %d)", round_i + 1)
            return True

        sid = identify(screen)
        if not is_post_run_overlay(screen):
            if sid in _COMBAT_SCREENS:
                log.warning(
                    "post-run dismiss abortado: pantalla de combate (%s), falso positivo?",
                    sid.value,
                )
                return False
            log.info("post-run: overlay cerrado (%s), espero lobby...", sid.value)
            if ctx.wait_for_lobby(timeout=12.0):
                return True
            return is_lobby(ctx.device.screenshot())

        tap = taps[round_i % len(taps)]
        log.info(
            "post-run ronda %d/%d screen=%s challenge_end=%s",
            round_i + 1,
            max_rounds,
            sid.value,
            is_challenge_ended_screen(screen),
        )
        dismiss_post_run_overlays(ctx, tap=tap)

        if ctx.wait_for_lobby(timeout=12.0):
            log.info("post-run: lobby OK tras tap (ronda %d)", round_i + 1)
            return True

    screen = ctx.device.screenshot()
    ok = is_lobby(screen)
    if not ok:
        tx, ty, ts = taps[0]
        log.error(
            "post-run FALLO tras %d rondas screen=%s last_tap=(%d,%d,%s)",
            max_rounds,
            identify(screen).value,
            tx,
            ty,
            ts,
        )
        path = dump_screen(ctx.device, "postrun_failed")
        if path:
            log.error("post-run dump: %s", path)
    return ok
