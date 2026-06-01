"""Identificación de pantalla actual mediante templates ancla.

Cada pantalla se reconoce por uno o más templates en templates/anchors/.
Si el template no existe todavía (pre-calibración), esa pantalla se omite
y identify() puede devolver UNKNOWN; el watchdog lo maneja.
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
    UNKNOWN = "unknown"


# Cada pantalla -> lista de anchors (filename relativo a templates/anchors/)
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

# Orden de chequeo: las pantallas modales (skill/devil/victory/defeat/popup)
# priman sobre las de fondo (battle/lobby) para no confundirlas.
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

# Solo pantallas relevantes durante combate (evita chequear lobby/mapa en cada loop).
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
                match = vision.find_template(screen, anchor)
            except FileNotFoundError:
                continue
            if match.confidence >= best_conf:
                best_conf = match.confidence
                best_id = screen_id
        if early_modal and best_id in _MODAL_SCREENS:
            return best_id
    return best_id


def identify(screen: np.ndarray, threshold: float = DEFAULT_THRESHOLD) -> ScreenId:
    return _identify_from_order(screen, CHECK_ORDER, threshold, early_modal=True)


def identify_combat(screen: np.ndarray, threshold: float = DEFAULT_THRESHOLD) -> ScreenId:
    return _identify_from_order(screen, COMBAT_CHECK_ORDER, threshold, early_modal=True)


def identify_live(device: Device, threshold: float = DEFAULT_THRESHOLD) -> ScreenId:
    return identify(device.screenshot(), threshold)


def is_lobby(screen: np.ndarray, threshold: float = 0.72) -> bool:
    try:
        return vision.matches(screen, "anchors/lobby.png", threshold=threshold)
    except FileNotFoundError:
        return False
