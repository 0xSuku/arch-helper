from __future__ import annotations

import unittest
from unittest.mock import patch

from bot.paths.daily import DailyPath
from bot.screens import ScreenId


class _Checks:
    def __init__(self) -> None:
        self.verified: list[str] = []
        self.force = False

    def mark_verified(self, claim_id: str) -> None:
        self.verified.append(claim_id)


class _Ctx:
    def __init__(self, screen: ScreenId) -> None:
        self._screen = screen
        self.back_count = 0
        self.return_to_lobby_count = 0

    def current_screen(self) -> ScreenId:
        return self._screen

    def back(self, *, settle: float = 1.0) -> None:
        self.back_count += 1

    def return_to_lobby(self) -> bool:
        self.return_to_lobby_count += 1
        return True


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

    def test_shackled_attempts_three_available_start_chances(self) -> None:
        path = _daily_path()
        path.ctx = _Ctx(ScreenId.UNKNOWN)
        path._is_shackled_combat_active = lambda: False
        path._is_shackled_jungle_popup = lambda: True
        starts: list[bool] = []
        path._start_shackled_jungle_run = lambda *, use_ad_ticket=False: starts.append(use_ad_ticket) or True
        path._run_one_shackled = lambda _runner: True

        with patch("bot.paths.daily.CombatRunner", lambda *args, **kwargs: object()), patch(
            "bot.paths.daily.sleep", lambda *_args, **_kwargs: None
        ):
            completed = path._events_shackled_jungle(from_popup=True)

        self.assertEqual(completed, 3)
        self.assertEqual(starts, [False, False, False])

    def test_shackled_stops_when_next_start_unavailable(self) -> None:
        path = _daily_path()
        path.ctx = _Ctx(ScreenId.UNKNOWN)
        path._is_shackled_combat_active = lambda: False
        path._is_shackled_jungle_popup = lambda: True
        attempts = [True, False]
        path._start_shackled_jungle_run = lambda *, use_ad_ticket=False: attempts.pop(0)
        path._run_one_shackled = lambda _runner: True

        with patch("bot.paths.daily.CombatRunner", lambda *args, **kwargs: object()), patch(
            "bot.paths.daily.sleep", lambda *_args, **_kwargs: None
        ):
            completed = path._events_shackled_jungle(from_popup=True)

        self.assertEqual(completed, 1)

    def test_privilege_returns_to_campaign_with_extra_back(self) -> None:
        path = _daily_path()
        backs: list[str] = []
        path._lobby_badge = lambda section, key: True
        path._opt = lambda section, key, **kwargs: True
        path._claim_all_generic = lambda section: None
        path._back = lambda: backs.append("back")
        path._go_campaign = lambda: backs.append("campaign")

        path.claim_privilege()

        self.assertEqual(backs, ["back", "back", "campaign"])
        self.assertIn("privilege", path.checks.verified)

    def test_shop_does_not_tap_gear_draw_x10_and_checks_all_free_sections(self) -> None:
        path = _daily_path()
        path.checks.force = True
        tabs: list[str] = []
        rewards: list[str] = []
        path._shop_tab_badge = lambda key: True

        def opt(section: str, key: str, **kwargs) -> bool:
            if key.startswith("tab_") or key == "top_up_sub_gold":
                tabs.append(key)
            return True

        path._opt = opt
        path._tap_optional_reward = lambda section, key, **kwargs: rewards.append(key) or True
        path._go_campaign = lambda: None

        path.claim_shop()

        self.assertNotIn("gear_draw_x10", rewards)
        self.assertIn("gear_chest_blue_free", rewards)
        self.assertIn("gear_chest_violet_free", rewards)
        self.assertIn("limited_offer_daily_free", rewards)
        self.assertIn("limited_offer_weekly_free", rewards)
        self.assertIn("limited_offer_monthly_free", rewards)
        self.assertIn("top_up_gold_free_1", rewards)
        self.assertIn("top_up_gold_free_2", rewards)
        self.assertIn("shop", path.checks.verified)

    def test_hunt_uses_quick_hunt_chances_counts(self) -> None:
        path = _daily_path()
        taps: list[str] = []
        path._opt = lambda section, key, **kwargs: True
        path._hunt_dismiss_rewards = lambda **kwargs: None
        path._tap_optional_reward = lambda section, key, **kwargs: taps.append(key) or True
        path._hunt_quick_chances = lambda key: {"quick_free": 0, "quick_x5": 3}[key]
        path._hunt_quick_available = lambda key: False

        path.claim_hunt()

        self.assertEqual(taps.count("quick_free"), 0)
        self.assertEqual(taps.count("quick_x5"), 3)
        self.assertIn("hunt", path.checks.verified)

    def test_hunt_skips_quick_claims_when_no_free_or_ticket_available(self) -> None:
        path = _daily_path()
        quick_taps: list[str] = []
        opened: list[str] = []

        def opt(section: str, key: str, **kwargs) -> bool:
            opened.append(key)
            return True

        path._opt = opt
        path._hunt_dismiss_rewards = lambda **kwargs: None
        path._tap_optional_reward = lambda section, key, **kwargs: quick_taps.append(key) or True
        path._hunt_quick_chances = lambda key: 0
        path._hunt_quick_available = lambda key: False
        path._lobby_badge = lambda section, key: False

        path.claim_hunt()

        self.assertIn("quick_hunt", opened)
        self.assertIn("close_quick_popup", opened)
        self.assertNotIn("quick_free", quick_taps)
        self.assertNotIn("quick_x5", quick_taps)

    def test_island_treasure_returns_to_campaign_with_extra_back(self) -> None:
        path = _daily_path()
        backs: list[str] = []
        path._opt = lambda section, key, **kwargs: True
        path._tap_optional_reward = lambda section, key, **kwargs: True
        path._back = lambda: backs.append("back")
        path._go_campaign = lambda: backs.append("campaign")

        result = path.claim_island_treasure()

        self.assertTrue(result)
        self.assertEqual(backs, ["back", "back", "campaign"])


if __name__ == "__main__":
    unittest.main()
