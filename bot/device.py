"""Device layer: ADB wrapper for the emulator (MuMu / LDPlayer).

Screenshots are returned as OpenCV BGR arrays in 900x1600 portrait space.
`input tap`/`input swipe` use the SAME coordinate system as the capture
(empirically confirmed), so there is no rotation or remapping.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

from .settings import DEFAULT_ADB, DEFAULT_SERIAL, EMULATOR_DIR, EMULATOR_INDEX, LDPLAYER_DIR, load_env

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "screenshots"


def _load_env() -> dict[str, str]:
    return load_env()


class Device:
    def __init__(self, adb_path: Path = DEFAULT_ADB, serial: str = DEFAULT_SERIAL) -> None:
        self.adb_path = Path(adb_path)
        self.serial = serial

    def _adb(self, *args: str, binary: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.adb_path), "-s", self.serial, *args],
            check=False,
            capture_output=True,
            text=not binary,
        )

    def connect(self) -> None:
        subprocess.run(
            [str(self.adb_path), "connect", self.serial],
            check=False,
            capture_output=True,
        )

    def is_connected(self) -> bool:
        result = subprocess.run(
            [str(self.adb_path), "devices"],
            check=False,
            capture_output=True,
            text=True,
        )
        return f"{self.serial}\tdevice" in (result.stdout or "")

    def screenshot(self, save_as: str | None = None, *, retry_reconnect: bool = True) -> np.ndarray:
        img = self._screenshot_execout()
        if img is None:
            img = self._screenshot_pull()
        if img is None and retry_reconnect:
            from .recovery import reconnect_adb

            if reconnect_adb(self, attempts=3, delay=1.0, port_timeout=12.0, restart_emulator=False):
                img = self._screenshot_execout()
                if img is None:
                    img = self._screenshot_pull()
        if img is None:
            raise RuntimeError("Could not capture emulator screen")
        if save_as:
            SHOTS.mkdir(exist_ok=True)
            cv2.imwrite(str(SHOTS / save_as), img)
        return img

    def _screenshot_execout(self) -> np.ndarray | None:
        result = self._adb("exec-out", "screencap", "-p", binary=True)
        data = result.stdout
        if not data or len(data) < 1024:
            return None
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        return img

    def _screenshot_pull(self) -> np.ndarray | None:
        remote = "/sdcard/archerov2_cap.png"
        self._adb("shell", "screencap", "-p", remote, binary=True)
        SHOTS.mkdir(exist_ok=True)
        local = SHOTS / "_pull.png"
        self._adb("pull", remote, str(local), binary=True)
        self._adb("shell", "rm", remote, binary=True)
        if not local.exists():
            return None
        return cv2.imread(str(local))

    def tap(self, x: float, y: float) -> None:
        self._adb("shell", "input", "tap", str(round(x)), str(round(y)))

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None:
        self._adb(
            "shell",
            "input",
            "swipe",
            str(round(x1)),
            str(round(y1)),
            str(round(x2)),
            str(round(y2)),
            str(duration_ms),
        )

    def back(self) -> None:
        self._adb("shell", "input", "keyevent", "4")

    def key(self, keycode: int) -> None:
        self._adb("shell", "input", "keyevent", str(keycode))


def sleep(seconds: float) -> None:
    time.sleep(seconds)
