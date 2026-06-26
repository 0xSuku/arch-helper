from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from bot.paths.daily import DailyPath
from bot.screens import ScreenId

ROOT = Path(__file__).resolve().parents[1]


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
    path.arena_max_power = 5.0
    path.arena_exit_early = False
    path.arena_confirm = False
    return path


class DailyPathRegressionTests(unittest.TestCase):
    def test_claim_arena_does_not_verify_when_no_fights_complete(self) -> None:
        path = _daily_path()
        path.arena_fights = 2
        path._arena_prepare_from_current_screen = lambda banner: False
        path._run_arena_fights = lambda mode, *, fights: 0
        path._leave_arena_to_campaign = lambda: None

        path.claim_arena()

        self.assertNotIn("arena", path.checks.verified)

    def test_arena_pick_prefers_highest_row_under_max_power(self) -> None:
        path = _daily_path()
        path.arena_max_power = 4.5
        powers = {1: 8.42, 2: 2.0, 3: 4.0, 4: 6.04, 5: 2.63}
        path._read_arena_opponent_power = lambda index: powers.get(index)

        rivals = {i: powers.get(i) for i in range(3, 6)}
        path._arena_read_rivals = lambda: rivals
        path._arena_refresh_opponents = lambda: None

        target = path._arena_pick_target()

        self.assertEqual(target, 3)

    def test_arena_pick_skips_when_all_above_max_after_refresh(self) -> None:
        path = _daily_path()
        path.arena_max_power = 4.3
        path._arena_refresh_opponents = lambda: None
        path._arena_read_rivals = lambda: {3: 5.0, 4: 5.1, 5: 4.8}

        target = path._arena_pick_target()

        self.assertIsNone(target)

    def test_arena_pick_uses_single_screenshot_read(self) -> None:
        path = _daily_path()
        path.arena_max_power = 4.3
        path._arena_refresh_opponents = lambda: None
        path._arena_read_rivals = lambda: {3: None, 4: None, 5: 1.11}

        target = path._arena_pick_target()

        self.assertEqual(target, 5)

    def test_peak_arena_recovery_reopens_peak_banner(self) -> None:
        path = _daily_path()
        path.ctx = _Ctx(ScreenId.ARENA_OPPONENTS)
        path.ctx.kill = type("K", (), {"check": lambda self: None})()
        opened_banners: list[str] = []
        path._open_arena_rivals_popup = lambda banner: opened_banners.append(banner) or True
        path._arena_recover_screen = lambda banner_key="arena_banner": True
        path._ensure_arena_challenge_popup = lambda banner: True
        path._is_arena_victory_screen = lambda: False
        path._is_arena_opponents_popup = lambda *args: True
        path._arena_read_rivals = lambda: {3: 1.0, 4: 1.0, 5: 1.0}
        path._arena_refresh_opponents = lambda: None
        path._arena_attack_opponent = lambda index: None
        path._wait_for_battle_start = lambda *, timeout: True
        path._wait_arena_victory_and_confirm = lambda: True
        path._arena_return_to_rivals = lambda banner: True

        with patch("bot.paths.daily.sleep", lambda *_args, **_kwargs: None):
            completed = path._run_arena_fights("peak_arena", fights=2)

        self.assertEqual(completed, 2)

    def test_arena_recover_from_personal_info(self) -> None:
        import cv2

        from bot.screens import ScreenId
        from bot.testing.fixtures import fixture_path

        path = _daily_path()
        path.ctx = _Ctx(ScreenId.UNKNOWN)
        path.ctx.kill = type("K", (), {"check": lambda self: None})()
        path.arena_reload_after_exit_s = 0.0
        dismissed: list[bool] = []

        personal = cv2.imread(str(ROOT / "screenshots" / "arena-after-exit-02s.png"))
        if personal is None:
            self.skipTest("Falta screenshots/arena-after-exit-02s.png")

        screens_seq = [personal, cv2.imread(str(fixture_path("arena", "opponents_popup.png")))]
        path.ctx.device = type("D", (), {"screenshot": lambda self: screens_seq.pop(0)})()

        path._dismiss_arena_personal_info = lambda: dismissed.append(True) or True
        path._arena_rivals_readable = lambda: True

        with patch("bot.paths.daily.sleep", lambda *_args, **_kwargs: None):
            ok = path._arena_recover_screen("arena_banner")

        self.assertTrue(ok)
        self.assertTrue(dismissed)

    def test_events_hub_includes_arena_opponents_popup(self) -> None:
        import cv2

        from bot.testing.fixtures import fixture_path

        path = _daily_path()
        path.ctx = _Ctx(ScreenId.UNKNOWN)
        popup = cv2.imread(str(fixture_path("arena", "opponents_popup.png")))
        self.assertIsNotNone(popup)
        self.assertTrue(path._is_events_hub(popup))

    def test_arena_read_state_on_fixture(self) -> None:
        import cv2

        from bot.testing.fixtures import fixture_path

        path = _daily_path()
        path.ctx = _Ctx(ScreenId.UNKNOWN)
        popup = cv2.imread(str(fixture_path("arena", "opponents_popup.png")))
        st = path._arena_read_state(popup)
        self.assertEqual(st.arena, ScreenId.ARENA_OPPONENTS)
        self.assertTrue(st.rivals_readable)

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
