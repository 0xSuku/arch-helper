"""Contexto base compartido por los paths: device + coords + failsafes + helpers."""
from __future__ import annotations

import time

import numpy as np

from .. import screens
from ..configs import Coords, Point
from ..device import Device, sleep
from ..failsafes import KillSwitch, MoneyGuard
from ..log import get_logger
from ..screens import ScreenId, is_lobby

log = get_logger("path")


class BotContext:
    def __init__(self, device: Device, coords: Coords | None = None) -> None:
        self.device = device
        self.coords = coords or Coords.load()
        self.kill = KillSwitch()
        self.money = MoneyGuard()
        self.hold_combat = False
        self.post_run_tap: tuple[int, int] | None = None

    def screenshot(self) -> np.ndarray:
        return self.device.screenshot()

    def tap(self, x: float, y: float, money_check: bool = True, settle: float = 0.0) -> None:
        self.kill.check()
        if money_check:
            self.money.assert_safe(self.device.screenshot(), (int(x), int(y)))
        self.device.tap(x, y)
        if settle:
            sleep(settle)

    def tap_point(self, section: str, key: str, money_check: bool = True, settle: float = 1.0) -> None:
        self.coords = Coords.load()
        point = self.coords.point(section, key)
        log.info("tap %s.%s (%d,%d) %s", section, key, point.x, point.y, point.label)
        self.tap(point.x, point.y, money_check=money_check, settle=settle)

    def tap_xy(self, point: Point, money_check: bool = True, settle: float = 1.0) -> None:
        self.tap(point.x, point.y, money_check=money_check, settle=settle)

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300, settle: float = 0.0) -> None:
        self.kill.check()
        self.device.swipe(x1, y1, x2, y2, duration_ms)
        if settle:
            sleep(settle)

    def back(self, settle: float = 1.0) -> None:
        self.kill.check()
        self.device.back()
        if settle:
            sleep(settle)

    def current_screen(self) -> ScreenId:
        return screens.identify(self.device.screenshot())

    def wait_screen(self, target: ScreenId, timeout: float = 12.0, interval: float = 0.6) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.kill.check()
            if screens.identify(self.device.screenshot()) == target:
                return True
            sleep(interval)
        return False

    def wait_until_not(
        self,
        avoid: ScreenId | set[ScreenId],
        timeout: float = 2.0,
        interval: float = 0.25,
    ) -> bool:
        avoids = {avoid} if isinstance(avoid, ScreenId) else set(avoid)
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.kill.check()
            if screens.identify(self.device.screenshot()) not in avoids:
                return True
            sleep(interval)
        return False

    def wait_for_lobby(self, timeout: float = 45.0, interval: float = 0.8) -> bool:
        """Espera regreso al lobby; tolera pantallas de carga/transición (UNKNOWN)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.kill.check()
            if self.current_screen() == ScreenId.LOBBY:
                return True
            sleep(interval)
        return self.current_screen() == ScreenId.LOBBY

    def return_to_lobby(self, max_back: int = 10) -> bool:
        from ..run_end_dismiss import dismiss_to_lobby, is_post_run_overlay

        screen = self.device.screenshot()
        if is_post_run_overlay(screen):
            return dismiss_to_lobby(self, max_rounds=max_back)

        for _ in range(max_back * 2):
            self.kill.check()
            if is_lobby(self.device.screenshot()):
                return True
            sid = self.current_screen()
            if sid in (ScreenId.VICTORY, ScreenId.DEFEAT) or is_post_run_overlay(self.device.screenshot()):
                dismiss_to_lobby(self, max_rounds=4)
                continue
            self.back(settle=1.0)
            sleep(0.4)
        return is_lobby(self.device.screenshot())
