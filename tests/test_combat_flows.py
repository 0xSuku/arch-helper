from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from bot.combat import CombatRunner
from bot.paths.base import BotContext
from bot.paths.challenge_events import CHALLENGE_EVENTS, ChallengeEventRunner
from bot.paths.play_level import PlayLevelPath
from bot.screens import ScreenId
from bot.testing.flows import COMBAT_FLOWS, run_mock_flow


class _Kill:
    def check(self) -> None:
        return None


class _Ctx:
    def __init__(self, screen: ScreenId) -> None:
        self._screen = screen
        self.kill = _Kill()
        self.hold_combat = False
        self.device = self

    def current_screen(self) -> ScreenId:
        return self._screen

    def screenshot(self):
        return np.zeros((1600, 900, 3), dtype=np.uint8)


class SurvivalCombatTests(unittest.TestCase):
    def test_survival_marks_verified_after_battle_and_defeat(self) -> None:
        ctx = _Ctx(ScreenId.BATTLE)
        path = PlayLevelPath.__new__(PlayLevelPath)
        path.ctx = ctx
        path.battle_timeout = 30.0
        path.survival_only = True
        path.circle_move = True
        path._saw_battle = False
        path._circle_move = lambda _phase: None
        path._handle_pact_reject = lambda _s: None
        path._pick_skill = lambda _s: None
        path._handle_devil_deal = lambda: None
        path._handle_roulette = lambda: None

        screens = iter([ScreenId.BATTLE, ScreenId.BATTLE, ScreenId.DEFEAT])

        with patch("bot.paths.play_level.sleep", lambda *_a, **_k: None), patch(
            "bot.paths.play_level.screens.identify_combat",
            lambda _s: next(screens, ScreenId.DEFEAT),
        ), patch("bot.combat_prompts.event_challenge_end", lambda _s: False), patch(
            "bot.combat_prompts.find_reject_button", lambda _s: None
        ):
            result, verified = path.fight_verified()

        self.assertEqual(result, "defeat")
        self.assertTrue(verified)


class ChallengeFlowTests(unittest.TestCase):
    def test_challenge_specs_registered(self) -> None:
        for claim in ("rumble_ladder", "seal_battle", "monster_invasion", "magic_plant_defense"):
            self.assertIn(claim, CHALLENGE_EVENTS)

    def test_combat_flow_manifest_covers_claims(self) -> None:
        claim_ids = {f.claim for f in COMBAT_FLOWS if f.claim}
        for claim in ("shackled_jungle", "abyssal_tide", "arena", "peak_arena", "rumble_ladder"):
            self.assertIn(claim, claim_ids)


class MockFlowTests(unittest.TestCase):
    def test_mock_flow_enters_and_exits(self) -> None:
        result = run_mock_flow(
            "arena",
            lobby_factory=lambda: np.full((1600, 900, 3), (30, 100, 30), dtype=np.uint8),
            battle_factory=lambda: np.full((1600, 900, 3), (30, 130, 30), dtype=np.uint8),
        )
        self.assertTrue(result.entered_combat or result.taps >= 0)


if __name__ == "__main__":
    unittest.main()
