"""Cierre de pantallas post-run (recompensas, runas, popups de detalle)."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import numpy as np
import cv2

from . import vision
from .device import sleep
from .log import dump_screen, get_logger
from .screens import ScreenId, identify, is_lobby

if TYPE_CHECKING:
    from .paths.base import BotContext

log = get_logger("run_end")

POST_RUN_TAP = (450, 1552)
# Debajo del grid, centro (evitar columna izq del loot que abre detalle de ítem).
FARM_POST_RUN_TAP = POST_RUN_TAP
POST_RUN_FARM_FALLBACK = (320, 1555)
POST_RUN_SCAN_Y = (1485, 1590)
POST_RUN_SCAN_X = (200, 700)
CHALLENGE_END_PIXEL = (450, 330)
CHALLENGE_ENDED_ANCHOR = "anchors/challenge_ended.png"
BANNER_SEARCH_REGION = (80, 240, 740, 160)
ROULETTE_SEARCH_REGION = (80, 90, 740, 180)
BANNER_TEMPLATE_THRESHOLD = 0.70
BANNER_TITLE_Y = (305, 355)
BANNER_TITLE_X = (250, 650)
POST_RUN_RECHECK_TIMEOUT = 4.0
POST_RUN_RECHECK_INTERVAL = 0.35


def configure_farm_ctx(ctx: BotContext) -> None:
    ctx.post_run_tap = FARM_POST_RUN_TAP


def _resolve_post_run_tap(ctx: BotContext) -> tuple[int, int, str]:
    custom = getattr(ctx, "post_run_tap", None)
    if custom:
        return int(custom[0]), int(custom[1]), "farm"
    return POST_RUN_TAP[0], POST_RUN_TAP[1], "default"


def post_run_dismiss_tap(_screen=None) -> tuple[int, int]:
    return POST_RUN_TAP


def _loot_like_score(patch) -> float:
    if patch.size == 0:
        return 0.0
    b = patch[:, :, 0].astype(int)
    g = patch[:, :, 1].astype(int)
    r = patch[:, :, 2].astype(int)
    vivid = (np.abs(r - g) + np.abs(g - b) + np.abs(r - b)).astype(float)
    bright = np.maximum(np.maximum(r, g), b).astype(float)
    return float(vivid.mean() * 0.6 + bright.mean() * 0.4)


def find_safe_post_run_tap(screen) -> tuple[int, int, str]:
    """Busca zona oscura/uniforme bajo el grid (no sobre ítems/runas)."""
    h, w = screen.shape[:2]
    y0, y1 = POST_RUN_SCAN_Y
    x0, x1 = POST_RUN_SCAN_X
    best_x, best_y = POST_RUN_TAP
    best_score = -1.0
    for y in range(y0, min(y1, h - 5), 6):
        for x in range(x0, min(x1, w - 5), 14):
            patch = screen[max(0, y - 6) : y + 7, max(0, x - 10) : x + 11]
            if patch.size == 0:
                continue
            mean = float(patch.mean())
            std = float(patch.std())
            loot = _loot_like_score(patch)
            # Preferir suelo vacío: oscuro, poco colorido, poco contraste de ítem.
            score = (220.0 - mean) + std * 0.3 - loot * 1.2
            if score > best_score:
                best_score = score
                best_x, best_y = x, y
    if best_score < 0:
        return POST_RUN_TAP[0], POST_RUN_TAP[1], "default"
    return best_x, best_y, "scanned"


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
        return vision.matches(
            screen,
            "anchors/roulette.png",
            threshold=0.68,
            region=ROULETTE_SEARCH_REGION,
        )
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
    panel = screen[int(h * 0.11) : int(h * 0.75), int(w * 0.03) : int(w * 0.97)]
    inner = screen[int(h * 0.19) : int(h * 0.71), int(w * 0.07) : int(w * 0.93)]
    close_area = screen[int(h * 0.12) : int(h * 0.21), int(w * 0.80) : int(w * 0.96)]
    if panel.size == 0 or inner.size == 0 or close_area.size == 0:
        return False

    panel_hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
    inner_hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
    close_hsv = cv2.cvtColor(close_area, cv2.COLOR_BGR2HSV)
    panel_beige = cv2.inRange(panel_hsv, (8, 35, 120), (40, 180, 255))
    inner_beige = cv2.inRange(inner_hsv, (8, 25, 120), (40, 180, 255))
    close_orange = cv2.inRange(close_hsv, (5, 70, 90), (35, 255, 255))

    panel_ratio = cv2.countNonZero(panel_beige) / float(panel_beige.size)
    inner_ratio = cv2.countNonZero(inner_beige) / float(inner_beige.size)
    close_ratio = cv2.countNonZero(close_orange) / float(close_orange.size)
    if panel_ratio >= 0.45 and inner_ratio >= 0.45 and close_ratio >= 0.12:
        return True

    return False


def is_item_detail_popup(screen) -> bool:
    if is_lobby(screen) or _roulette_on_field(screen):
        return False
    if not _beige_item_card_heuristic(screen):
        return False
    return True


def _item_detail_close_point(screen) -> tuple[int, int]:
    h, w = screen.shape[:2]
    x0 = int(w * 0.72)
    y0 = int(h * 0.10)
    x1 = int(w * 0.97)
    y1 = int(h * 0.32)
    region = screen[y0:y1, x0:x1]
    if region.size == 0:
        return 810, 257
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, (5, 70, 90), (35, 255, 255))
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(orange, 8)
    best_idx = -1
    best_area = 0
    for i in range(1, count):
        area = int(stats[i, cv2.CC_STAT_AREA])
        width = int(stats[i, cv2.CC_STAT_WIDTH])
        height = int(stats[i, cv2.CC_STAT_HEIGHT])
        if area > best_area and width >= 18 and height >= 18:
            best_idx = i
            best_area = area
    if best_idx < 0 or best_area < 120:
        return 810, 257
    cx, cy = centroids[best_idx]
    return int(round(x0 + cx)), int(round(y0 + cy))


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

    farm_mode = getattr(ctx, "post_run_tap", None) is not None
    try:
        p = ctx.coords.point("run_end", "continue")
        add(p.x, p.y, "coords")
    except (KeyError, ValueError):
        pass
    add(POST_RUN_TAP[0], POST_RUN_TAP[1], "default")
    if farm_mode:
        try:
            p = ctx.coords.point("run_end", "continue_farm")
            if (p.x, p.y) != (POST_RUN_TAP[0], POST_RUN_TAP[1]):
                add(p.x, p.y, "coords_farm")
        except (KeyError, ValueError):
            pass
        fx, fy = POST_RUN_FARM_FALLBACK
        if (fx, fy) not in seen:
            add(fx, fy, "farm_fallback")
    return taps


def _tap_dismiss(ctx: BotContext, x: int, y: int, src: str) -> None:
    log.info("tap post-run (%d,%d) src=%s", x, y, src)
    ctx.tap(x, y, money_check=False, settle=0.0)
    sleep(0.45)


def _close_item_detail_popup(ctx: BotContext) -> None:
    log.info("post-run: popup ítem -> cerrar")
    ctx.back(settle=0.35)
    screen = ctx.device.screenshot()
    if is_lobby(screen) or not is_item_detail_popup(screen):
        return
    x, y = _item_detail_close_point(screen)
    log.info("post-run: popup ítem persiste -> tap X (%d,%d)", x, y)
    ctx.tap(x, y, money_check=False, settle=0.45)


def _wait_for_lobby_or_retry(ctx: BotContext, *, timeout: float = POST_RUN_RECHECK_TIMEOUT) -> bool:
    deadline = time.time() + timeout
    overlay_seen = 0
    while time.time() < deadline:
        ctx.kill.check()
        screen = ctx.device.screenshot()
        if is_lobby(screen):
            return True
        if is_item_detail_popup(screen):
            _close_item_detail_popup(ctx)
            overlay_seen = 0
            continue
        if is_post_run_overlay(screen):
            overlay_seen += 1
            if overlay_seen >= 2:
                return False
        else:
            overlay_seen = 0
        sleep(POST_RUN_RECHECK_INTERVAL)
    return is_lobby(ctx.device.screenshot())


def dismiss_post_run_overlays(ctx: BotContext, *, tap: tuple[int, int, str] | None = None) -> None:
    screen = ctx.device.screenshot()
    if is_lobby(screen):
        return
    if is_item_detail_popup(screen):
        _close_item_detail_popup(ctx)
        if is_lobby(ctx.device.screenshot()):
            return
        screen = ctx.device.screenshot()
    if tap is None:
        if getattr(ctx, "post_run_tap", None) and (
            is_challenge_ended_screen(screen) or _loot_grid_heuristic(screen)
        ):
            x, y, src = find_safe_post_run_tap(screen)
        else:
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
        if getattr(ctx, "post_run_tap", None) and (
            is_challenge_ended_screen(screen)
            or _loot_grid_heuristic(screen)
            or is_item_detail_popup(screen)
        ):
            tap = None
        log.info(
            "post-run ronda %d/%d screen=%s challenge_end=%s",
            round_i + 1,
            max_rounds,
            sid.value,
            is_challenge_ended_screen(screen),
        )
        dismiss_post_run_overlays(ctx, tap=tap)

        if _wait_for_lobby_or_retry(ctx):
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
