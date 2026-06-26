"""Failsafes: cross-cutting safety guards for the bot.

- StopRequested / PathAborted / MoneyBlocked: control exceptions.
- KillSwitch: STOP sentinel file + Ctrl+C.
- MoneyGuard: never tap real-money purchase buttons.
- StuckDetector: detects frozen screens and triggers recovery.
- UnknownScreenWatchdog: aborts if the screen is unrecognized for too long.
- BattleTimeout: ends a run that exceeds its maximum duration.
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
    """The user asked to stop the bot (STOP file or Ctrl+C)."""


class PathAborted(Exception):
    """A path aborted due to an unrecoverable condition (stuck/unknown)."""


class MoneyBlocked(Exception):
    """A tap was blocked because a real-money price tag was detected."""


class KillSwitch:
    def __init__(self) -> None:
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def check(self) -> None:
        if self._stop or STOP_FILE.exists():
            raise StopRequested("Kill switch activated (STOP file or Ctrl+C)")


class MoneyGuard:
    """Abort any action if a price tag ($) is detected on screen.

    If the buttons/money_tag.png template does not exist yet, the guard stays inactive
    (cannot produce false positives), but a warning is logged once.
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
                    "MoneyGuard inactive: missing templates/%s. Calibrate it for maximum safety.",
                    MONEY_TEMPLATE,
                )
                self._warned = True
            return []

    def assert_safe(self, screen: np.ndarray, point: tuple[int, int] | None = None) -> None:
        for m in self._money_matches(screen):
            if point is None:
                raise MoneyBlocked("Price tag detected on screen")
            if abs(m.cx - point[0]) <= self.radius and abs(m.cy - point[1]) <= self.radius:
                raise MoneyBlocked(
                    f"Price tag near ({point[0]},{point[1]}); tap blocked"
                )


class StuckDetector:
    """Detects that the screen has not changed for `patience` seconds."""

    def __init__(self, patience: float = 8.0, change_threshold: float = 0.01) -> None:
        self.patience = patience
        self.change_threshold = change_threshold
        self._last: np.ndarray | None = None
        self._since = time.time()

    def reset(self) -> None:
        self._last = None
        self._since = time.time()

    def update(self, screen: np.ndarray) -> bool:
        """Returns True if the screen is considered stuck."""
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
