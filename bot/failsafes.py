"""Failsafes: guardas de seguridad transversales al bot.

- StopRequested / PathAborted / MoneyBlocked: excepciones de control.
- KillSwitch: archivo centinela STOP + Ctrl+C.
- MoneyGuard: nunca tocar botones de compra con dinero real.
- StuckDetector: detecta pantallas congeladas y dispara recovery.
- UnknownScreenWatchdog: aborta si no se reconoce la pantalla por mucho tiempo.
- BattleTimeout: corta una partida que excede su duración máxima.
"""
from __future__ import annotations

import time

import numpy as np

from . import vision
from .device import Device, ROOT
from .log import get_logger

log = get_logger("failsafes")

STOP_FILE = ROOT / "STOP"
MONEY_TEMPLATE = "buttons/money_tag.png"


class StopRequested(Exception):
    """El usuario pidió detener el bot (archivo STOP o Ctrl+C)."""


class PathAborted(Exception):
    """Un path se abortó por una condición irrecuperable (stuck/unknown)."""


class MoneyBlocked(Exception):
    """Se bloqueó un tap por detectarse un precio en dinero real."""


class KillSwitch:
    def __init__(self) -> None:
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def check(self) -> None:
        if self._stop or STOP_FILE.exists():
            raise StopRequested("Kill-switch activado (archivo STOP o Ctrl+C)")


class MoneyGuard:
    """Aborta cualquier acción si detecta una etiqueta de precio ($) en pantalla.

    Si el template buttons/money_tag.png no existe aún, el guard queda inactivo
    (no puede dar falsos positivos), pero se avisa una vez.
    """

    def __init__(self, threshold: float = 0.86, radius: int = 220) -> None:
        self.threshold = threshold
        self.radius = radius
        self._warned = False

    def _money_matches(self, screen: np.ndarray) -> list[vision.Match]:
        try:
            return vision.find_all(screen, MONEY_TEMPLATE, threshold=self.threshold)
        except FileNotFoundError:
            if not self._warned:
                log.warning(
                    "MoneyGuard inactivo: falta templates/%s. Calibralo para máxima seguridad.",
                    MONEY_TEMPLATE,
                )
                self._warned = True
            return []

    def assert_safe(self, screen: np.ndarray, point: tuple[int, int] | None = None) -> None:
        for m in self._money_matches(screen):
            if point is None:
                raise MoneyBlocked("Etiqueta de precio detectada en pantalla")
            if abs(m.cx - point[0]) <= self.radius and abs(m.cy - point[1]) <= self.radius:
                raise MoneyBlocked(
                    f"Etiqueta de precio cerca de ({point[0]},{point[1]}); tap bloqueado"
                )


class StuckDetector:
    """Detecta que la pantalla no cambió durante `patience` segundos."""

    def __init__(self, patience: float = 8.0, change_threshold: float = 0.01) -> None:
        self.patience = patience
        self.change_threshold = change_threshold
        self._last: np.ndarray | None = None
        self._since = time.time()

    def reset(self) -> None:
        self._last = None
        self._since = time.time()

    def update(self, screen: np.ndarray) -> bool:
        """Devuelve True si se considera 'stuck'."""
        if self._last is None:
            self._last = screen
            self._since = time.time()
            return False
        if vision.screen_changed(self._last, screen, self.change_threshold):
            self._last = screen
            self._since = time.time()
            return False
        return (time.time() - self._since) >= self.patience


class UnknownScreenWatchdog:
    def __init__(self, patience: float = 12.0) -> None:
        self.patience = patience
        self._since: float | None = None

    def reset(self) -> None:
        self._since = None

    def update(self, is_unknown: bool) -> bool:
        if not is_unknown:
            self._since = None
            return False
        if self._since is None:
            self._since = time.time()
            return False
        return (time.time() - self._since) >= self.patience


class BattleTimeout:
    def __init__(self, max_seconds: float = 180.0) -> None:
        self.max_seconds = max_seconds
        self._start = time.time()

    def reset(self) -> None:
        self._start = time.time()

    @property
    def elapsed(self) -> float:
        return time.time() - self._start

    def expired(self) -> bool:
        return self.elapsed >= self.max_seconds


def clear_stop_file() -> None:
    try:
        STOP_FILE.unlink()
    except FileNotFoundError:
        pass
