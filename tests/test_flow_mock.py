from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.paths.daily import DailyPath
from bot.paths.base import BotContext
from bot.testing.mock_device import replay_device

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "screenshots" / "arena-debug.png"


class FlowMockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        dest = ROOT / "tests" / "fixtures" / "screens" / "arena" / "opponents_popup.png"
        if SOURCE.exists() and not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE, dest)

    def test_arena_pick_scans_under_max_power(self) -> None:
        if not (ROOT / "tests" / "fixtures" / "screens" / "arena" / "opponents_popup.png").exists():
            self.skipTest("fixture missing")
        device = replay_device("arena/opponents_popup.png")
        ctx = BotContext(device)
        path = DailyPath(ctx, force=True, arena_max_power=6.0)
        path._is_arena_opponents_popup = lambda *args, **kwargs: True
        target = path._arena_pick_target()
        self.assertGreaterEqual(target, 1)
        self.assertLessEqual(target, 5)

    def test_leave_arena_taps_back_from_popup(self) -> None:
        device = replay_device("arena/opponents_popup.png")
        ctx = BotContext(device)
        path = DailyPath(ctx, force=True)
        path._is_arena_opponents_popup = lambda: True
        path._back = lambda: device.back()
        path._go_campaign = lambda: None
        path._leave_arena_to_campaign()
        self.assertGreaterEqual(device.backs, 1)


if __name__ == "__main__":
    unittest.main()
