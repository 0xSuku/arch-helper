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

    def test_all_powers_on_fixture(self) -> None:
        expected = [8.33, 10.62, 3.32, 5.14, 1.55]
        for index, exp in enumerate(expected):
            power = vision.read_arena_opponent_power(self.screen, index)
            self.assertIsNotNone(power, f"rival #{index + 1}")
            assert power is not None
            self.assertAlmostEqual(power, exp, places=2)

    def test_weakest_opponent_readable(self) -> None:
        powers: list[float] = []
        for index in range(5):
            power = vision.read_arena_opponent_power(self.screen, index)
            if power is not None:
                powers.append(power)
        self.assertTrue(any(p <= 3.0 for p in powers))

    def test_victory_not_detected_on_opponents_popup(self) -> None:
        from types import SimpleNamespace

        from bot.paths.daily import DailyPath

        path = object.__new__(DailyPath)
        path.ctx = SimpleNamespace(device=None)
        self.assertFalse(path._is_arena_victory_screen(self.screen))

    def test_identify_arena_opponents_on_fixture(self) -> None:
        from bot.screens import ScreenId, identify

        self.assertEqual(identify(self.screen), ScreenId.ARENA_OPPONENTS)

    def test_leaderboard_detected_on_peak_fixture(self) -> None:
        from bot.screens import ScreenId, identify_arena

        path = fixture_path("arena", "leaderboard_peak.png")
        if not path.exists():
            self.skipTest("Falta fixture arena/leaderboard_peak.png")
        screen = cv2.imread(str(path))
        self.assertTrue(vision.is_arena_leaderboard(screen))
        self.assertEqual(identify_arena(screen), ScreenId.ARENA_LEADERBOARD)

    def test_rival_challenge_tap_on_right_side(self) -> None:
        tap = vision.find_arena_rival_challenge_tap(self.screen, 888)
        self.assertIsNotNone(tap)
        assert tap is not None
        x, y = tap
        self.assertEqual(x, 800)
        self.assertGreater(y, 820)
        self.assertLess(y, 960)


if __name__ == "__main__":
    unittest.main()
