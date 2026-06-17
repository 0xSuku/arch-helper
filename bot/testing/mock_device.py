from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..device import Device


@dataclass
class ScreenshotDevice:
    """Device fake que reproduce una secuencia de capturas."""

    frames: list[np.ndarray]
    index: int = 0
    taps: list[tuple[int, int]] = field(default_factory=list)
    swipes: list[tuple[int, int, int, int, int]] = field(default_factory=list)
    backs: int = 0

    def screenshot(self, save_as: str | None = None, *, retry_reconnect: bool = True) -> np.ndarray:
        _ = save_as
        _ = retry_reconnect
        if not self.frames:
            raise RuntimeError("ScreenshotDevice sin frames")
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return frame.copy()

    def tap(self, x: float, y: float) -> None:
        self.taps.append((round(x), round(y)))

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None:
        self.swipes.append((round(x1), round(y1), round(x2), round(y2), duration_ms))

    def back(self) -> None:
        self.backs += 1

    def connect(self) -> None:
        return None

    def is_connected(self) -> bool:
        return True


def replay_device(*paths: str) -> ScreenshotDevice:
    from .fixtures import load_fixture

    return ScreenshotDevice([load_fixture(path) for path in paths])
