"""Detección de popups de combate (pacto diablo / activos) que no matchean anchors."""
from __future__ import annotations

import numpy as np

SHACKLED_CHALLENGE_END_PIXEL = (450, 330)


def is_shackled_challenge_end(screen) -> bool:
    from .run_end_dismiss import is_challenge_ended_screen

    return is_challenge_ended_screen(screen)


def event_challenge_end(screen) -> bool:
    """Challenge has ended real: no skill select / ruleta / pacto encima."""
    from .run_end_dismiss import is_challenge_ended_screen
    from .screens import ScreenId, identify_combat

    if not is_challenge_ended_screen(screen):
        return False
    sid = identify_combat(screen)
    return sid not in (
        ScreenId.SKILL_SELECT,
        ScreenId.ROULETTE,
        ScreenId.DEVIL_DEAL,
    )


def dismiss_shackled_challenge_end(ctx) -> None:
    try:
        ctx.tap_point("events", "shackled_jungle_dismiss_end", money_check=False, settle=0.5)
    except ValueError:
        try:
            ctx.tap_point("events", "dismiss_rewards", money_check=False, settle=0.5)
        except ValueError:
            ctx.tap(450, 1552, money_check=False, settle=0.5)


def detect_pact_offer(screen: np.ndarray) -> bool:
    return find_reject_button(screen) is not None


def _red_button_cluster(screen: np.ndarray, cx: int, cy: int, *, min_pixels: int = 6) -> bool:
    h, w = screen.shape[:2]
    count = 0
    for dy in range(-12, 13, 4):
        for dx in range(-35, 36, 4):
            x, y = cx + dx, cy + dy
            if not (0 <= y < h and 0 <= x < w):
                continue
            b, g, r = screen[y, x]
            if int(r) > 180 and int(g) < 100 and int(b) < 100:
                count += 1
    return count >= min_pixels


def find_reject_button(screen: np.ndarray) -> tuple[int, int] | None:
    from .run_end_dismiss import is_post_run_context

    if is_post_run_context(screen):
        return None

    best_y, best_x, best_r = 0, 0, 0.0
    for y in range(1260, 1296, 4):
        for x in range(120, 221, 4):
            b, g, r = screen[y, x]
            if r > 180 and g < 100 and b < 100 and r > best_r:
                best_r, best_x, best_y = float(r), x, y
    if best_r <= 0:
        return None
    if not _red_button_cluster(screen, best_x, best_y):
        return None
    return best_x, best_y

def scan_and_reject_coords(screen: np.ndarray) -> tuple[int, int] | None:
    return find_reject_button(screen)
