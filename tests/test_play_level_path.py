from __future__ import annotations

import unittest
from unittest.mock import patch

from bot.paths.play_level import PlayLevelPath
from bot.screens import ScreenId


class _Ctx:
    def __init__(self, screen: ScreenId) -> None:
        self._screen = screen
        self.back_count = 0
        self.return_to_lobby_count = 0
        self.taps: list[tuple[str, str]] = []
        self.kill = self

    def current_screen(self) -> ScreenId:
        return self._screen

    def check(self) -> None:
        return None

    def back(self, *, settle: float = 1.0) -> None:
        self.back_count += 1

    def return_to_lobby(self) -> bool:
        self.return_to_lobby_count += 1
        return True

    def tap_point(self, section: str, key: str, **_kwargs) -> None:
        self.taps.append((section, key))


class PlayLevelPathTests(unittest.TestCase):
    def test_enter_level_taps_campaign_tab_before_start(self) -> None:
        ctx = _Ctx(ScreenId.LOBBY)
        path = PlayLevelPath.__new__(PlayLevelPath)
        path.ctx = ctx
        path._ensure_level_50 = lambda: True
        path._wait_combat_start = lambda: True

        self.assertTrue(path._enter_level())

        self.assertEqual(ctx.taps[:2], [("nav", "campaign"), ("lobby", "campaign_start")])

    def test_wait_combat_start_stops_early_on_popup(self) -> None:
        ctx = _Ctx(ScreenId.POPUP)
        path = PlayLevelPath.__new__(PlayLevelPath)
        path.ctx = ctx
        path.start_timeout = 40.0

        with patch("bot.paths.play_level.sleep", lambda *_args, **_kwargs: None):
            self.assertFalse(path._wait_combat_start())

        self.assertEqual(ctx.back_count, 1)
        self.assertEqual(ctx.return_to_lobby_count, 1)


if __name__ == "__main__":
    unittest.main()
