from __future__ import annotations

import shutil
import unittest
from pathlib import Path

import cv2

from bot import vision
from bot.testing.fixtures import FIXTURES_DIR, fixture_path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "screenshots" / "arena-debug.png"


class ArenaVisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if SOURCE.exists():
            dest = fixture_path("arena", "opponents_popup.png")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(SOURCE, dest)

    def setUp(self) -> None:
        if not fixture_path("arena", "opponents_popup.png").exists():
            self.skipTest("Falta fixture arena/opponents_popup.png")
        self.screen = cv2.imread(str(fixture_path("arena", "opponents_popup.png")))

    def test_opponents_popup_detected(self) -> None:
        self.assertTrue(vision.is_arena_opponents_popup(self.screen))

    def test_power_rows_detected(self) -> None:
        rows = vision.find_arena_power_row_ys(self.screen)
        self.assertGreaterEqual(len(rows), 5)

    def test_weakest_opponent_readable(self) -> None:
        powers: list[float] = []
        for index in range(5):
            power = vision.read_arena_opponent_power(self.screen, index)
            if power is not None:
                powers.append(power)
        self.assertTrue(any(p <= 3.0 for p in powers))


if __name__ == "__main__":
    unittest.main()
