from __future__ import annotations

import unittest
from unittest.mock import patch

from bot.paths.daily import DailyPath
from bot.screens import ScreenId


class _Checks:
    def __init__(self) -> None:
        self.verified: list[str] = []

    def mark_verified(self, claim_id: str) -> None:
        self.verified.append(claim_id)


class _Ctx:
    def __init__(self, screen: ScreenId) -> None:
        self._screen = screen

    def current_screen(self) -> ScreenId:
        return self._screen


def _daily_path() -> DailyPath:
    path = object.__new__(DailyPath)
    path.checks = _Checks()
    return path


class DailyPathRegressionTests(unittest.TestCase):
    def test_claim_arena_does_not_verify_when_no_fights_complete(self) -> None:
        path = _daily_path()
        path.arena_fights = 2
        path._is_arena_opponents_popup = lambda: True
        path._ensure_events_hub = lambda: False
        path._run_arena_fights = lambda mode, *, fights: 0
        path._leave_arena_to_campaign = lambda: None

        path.claim_arena()

        self.assertNotIn("arena", path.checks.verified)

    def test_peak_arena_recovery_reopens_peak_banner(self) -> None:
        path = _daily_path()
        opened_banners: list[str] = []
        path._open_arena_rivals_popup = lambda banner: opened_banners.append(banner) or True
        path._is_arena_victory_screen = lambda: False
        path._is_arena_opponents_popup = lambda *args: True
        path._read_arena_opponent_power = lambda index: 1.0
        path._arena_attack_opponent = lambda index: None
        path._wait_for_battle_start = lambda *, timeout: False
        path._wait_arena_victory_and_confirm = lambda: True
        path._wait_arena_opponents = lambda *, timeout: False

        with patch("bot.paths.daily.sleep", lambda *_args, **_kwargs: None):
            completed = path._run_arena_fights("peak_arena", fights=1)

        self.assertEqual(completed, 1)
        self.assertEqual(opened_banners, ["peak_arena_banner", "peak_arena_banner"])

    def test_single_abyssal_claim_does_not_resume_generic_combat(self) -> None:
        path = _daily_path()
        path.ctx = _Ctx(ScreenId.BATTLE)
        path._is_abyssal_tide_popup = lambda: False
        path._is_events_hub = lambda: False

        self.assertFalse(path._solo_claim_resume(["abyssal_tide"]))

    def test_abyssal_claim_opens_popup_instead_of_resuming_generic_combat(self) -> None:
        path = _daily_path()
        path.ctx = _Ctx(ScreenId.BATTLE)
        path._is_abyssal_tide_popup = lambda: False
        calls: list[dict[str, bool]] = []

        def events_abyssal_tide(**kwargs: bool) -> int:
            calls.append(kwargs)
            return 0

        path._events_abyssal_tide = events_abyssal_tide
        path._exit_abyssal_tide = lambda: None

        path.claim_abyssal_tide()

        self.assertEqual(calls, [{}])


if __name__ == "__main__":
    unittest.main()
