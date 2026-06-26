"""Identify the current screen via anchor templates.

Each screen is recognized by one or more templates in templates/anchors/.
If a template does not exist yet (pre-calibration), that screen is skipped
and identify() may return UNKNOWN; the watchdog handles it.
"""
from __future__ import annotations

from enum import Enum

import numpy as np

from . import vision
from .device import Device


class ScreenId(str, Enum):
    LOBBY = "lobby"
    LEVEL_SELECT = "level_select"
    BATTLE = "battle"
    ROULETTE = "roulette"
    SKILL_SELECT = "skill_select"
    DEVIL_DEAL = "devil_deal"
    VICTORY = "victory"
    DEFEAT = "defeat"
    POPUP = "popup"
    ARENA_PERSONAL_INFO = "arena_personal_info"
    ARENA_OPPONENTS = "arena_opponents"
    ARENA_LEADERBOARD = "arena_leaderboard"
    UNKNOWN = "unknown"


# Each screen -> anchor list (filename relative to templates/anchors/)
ANCHORS: dict[ScreenId, list[str]] = {
    ScreenId.LOBBY: ["anchors/lobby.png"],
    ScreenId.LEVEL_SELECT: ["anchors/level_select.png"],
    ScreenId.BATTLE: ["anchors/battle_hud.png"],
    ScreenId.ROULETTE: ["anchors/roulette.png"],
    ScreenId.SKILL_SELECT: ["anchors/skill_select.png"],
    ScreenId.DEVIL_DEAL: ["anchors/devil_deal.png"],
    ScreenId.VICTORY: ["anchors/victory.png"],
    ScreenId.DEFEAT: ["anchors/defeat.png"],
    ScreenId.POPUP: ["anchors/popup.png"],
}

ANCHOR_REGIONS: dict[str, vision.Region] = {
    "anchors/battle_hud.png": (0, 35, 180, 180),
    "anchors/roulette.png": (80, 90, 740, 180),
    "anchors/skill_select.png": (0, 300, 900, 180),
    "anchors/devil_deal.png": (0, 220, 900, 260),
    "anchors/victory.png": (60, 240, 780, 180),
    "anchors/defeat.png": (60, 240, 780, 180),
    "anchors/challenge_ended.png": (60, 240, 780, 180),
}

# Check order: modal screens (skill/devil/victory/defeat/popup)
# take priority over background (battle/lobby) to avoid confusion.
CHECK_ORDER = [
    ScreenId.SKILL_SELECT,
    ScreenId.DEVIL_DEAL,
    ScreenId.ROULETTE,
    ScreenId.VICTORY,
    ScreenId.DEFEAT,
    ScreenId.POPUP,
    ScreenId.LEVEL_SELECT,
    ScreenId.BATTLE,
    ScreenId.LOBBY,
]

# Combat-relevant screens only (avoids checking lobby/map every loop).
COMBAT_CHECK_ORDER = [
    ScreenId.SKILL_SELECT,
    ScreenId.DEVIL_DEAL,
    ScreenId.ROULETTE,
    ScreenId.VICTORY,
    ScreenId.DEFEAT,
    ScreenId.BATTLE,
]

_MODAL_SCREENS = frozenset({
    ScreenId.SKILL_SELECT,
    ScreenId.DEVIL_DEAL,
    ScreenId.ROULETTE,
    ScreenId.VICTORY,
    ScreenId.DEFEAT,
})

DEFAULT_THRESHOLD = 0.78


def identify_arena(screen: np.ndarray) -> ScreenId | None:
    try:
        if vision.matches(screen, "anchors/lobby.png", threshold=0.72):
            return None
    except FileNotFoundError:
        pass
    if vision.is_arena_personal_info_overlay(screen):
        return ScreenId.ARENA_PERSONAL_INFO
    if vision.is_arena_opponents_popup(screen):
        return ScreenId.ARENA_OPPONENTS
    if vision.is_arena_leaderboard(screen):
        return ScreenId.ARENA_LEADERBOARD
    return None


def _identify_from_order(
    screen: np.ndarray,
    order: list[ScreenId],
    threshold: float,
    early_modal: bool,
) -> ScreenId:
    best_id = ScreenId.UNKNOWN
    best_conf = threshold
    for screen_id in order:
        for anchor in ANCHORS.get(screen_id, []):
            try:
                match = vision.find_template(screen, anchor, region=ANCHOR_REGIONS.get(anchor))
            except FileNotFoundError:
                continue
            if match.confidence >= best_conf:
                best_conf = match.confidence
                best_id = screen_id
        if early_modal and best_id in _MODAL_SCREENS:
            return best_id
    return best_id


def identify(screen: np.ndarray, threshold: float = DEFAULT_THRESHOLD) -> ScreenId:
    arena = identify_arena(screen)
    if arena is not None:
        return arena
    return _identify_from_order(screen, CHECK_ORDER, threshold, early_modal=True)


def identify_combat(screen: np.ndarray, threshold: float = DEFAULT_THRESHOLD) -> ScreenId:
    return _identify_from_order(screen, COMBAT_CHECK_ORDER, threshold, early_modal=True)


def identify_live(device: Device, threshold: float = DEFAULT_THRESHOLD) -> ScreenId:
    return identify(device.screenshot(), threshold)


def is_lobby(screen: np.ndarray, threshold: float = 0.72) -> bool:
    try:
        if vision.matches(screen, "anchors/lobby.png", threshold=threshold):
            return True
    except FileNotFoundError:
        pass
    return identify(screen, threshold=threshold) == ScreenId.LOBBY
