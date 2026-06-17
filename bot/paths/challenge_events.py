"""Eventos de la pestaña Challenge (Events): entrada, combate y salida al lobby."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from ..combat import CombatRunner
from ..device import sleep
from ..log import get_logger
from ..screens import ScreenId, is_lobby
from .base import BotContext

log = get_logger("challenge")

CombatKind = Literal["survival", "skills_only", "afk"]


@dataclass(frozen=True)
class ChallengeEventSpec:
    claim_id: str
    banner_key: str
    start_key: str
    runs: int = 1
    battle_timeout: float = 270.0
    combat: CombatKind = "survival"
    scroll_before_open: bool = False


CHALLENGE_EVENTS: dict[str, ChallengeEventSpec] = {
    "rumble_ladder": ChallengeEventSpec(
        "rumble_ladder",
        "rumble_ladder_banner",
        "rumble_ladder_start",
        runs=1,
        battle_timeout=300.0,
        combat="survival",
    ),
    "seal_battle": ChallengeEventSpec(
        "seal_battle",
        "seal_battle_banner",
        "seal_battle_start",
        runs=1,
        battle_timeout=270.0,
        combat="survival",
    ),
    "monster_invasion": ChallengeEventSpec(
        "monster_invasion",
        "monster_invasion_banner",
        "monster_invasion_start",
        runs=1,
        battle_timeout=270.0,
        combat="survival",
    ),
    "magic_plant_defense": ChallengeEventSpec(
        "magic_plant_defense",
        "magic_plant_defense_banner",
        "magic_plant_defense_start",
        runs=1,
        battle_timeout=270.0,
        combat="survival",
    ),
}


class ChallengeEventRunner:
    def __init__(self, ctx: BotContext) -> None:
        self.ctx = ctx

    def run(self, spec: ChallengeEventSpec, *, from_popup: bool = False) -> int:
        log.info("  %s (hasta %d run, %s)", spec.claim_id, spec.runs, spec.combat)
        completed = 0
        self.ctx.hold_combat = True
        try:
            if not from_popup and not self._open_popup(spec):
                return 0
            runner = self._combat_runner(spec)
            for n in range(spec.runs):
                log.info("    run %d/%d", n + 1, spec.runs)
                if not self._start_run(spec):
                    log.info("    Start no disponible; corto")
                    break
                if self._run_combat(runner, spec):
                    completed += 1
                sleep(0.8)
        finally:
            self.ctx.hold_combat = False
        return completed

    def exit_to_campaign(self, spec: ChallengeEventSpec) -> None:
        from ..combat_prompts import dismiss_shackled_challenge_end, event_challenge_end
        from ..run_end_dismiss import needs_post_run_dismiss

        combat_screens = frozenset({
            ScreenId.BATTLE,
            ScreenId.SKILL_SELECT,
            ScreenId.ROULETTE,
            ScreenId.DEVIL_DEAL,
        })

        if is_lobby(self.ctx.device.screenshot()):
            return
        log.info("  Saliendo de %s -> lobby campaña", spec.claim_id)
        for _ in range(12):
            self.ctx.kill.check()
            img = self.ctx.device.screenshot()
            if is_lobby(img):
                return
            sid = self.ctx.current_screen()
            if sid in combat_screens:
                if needs_post_run_dismiss(img):
                    dismiss_shackled_challenge_end(self.ctx)
                    sleep(0.8)
                else:
                    sleep(0.5)
                continue
            if event_challenge_end(img) or needs_post_run_dismiss(img):
                dismiss_shackled_challenge_end(self.ctx)
                sleep(0.8)
                continue
            if self._is_popup(img, spec):
                self.ctx.back(settle=0.8)
                sleep(0.6)
                continue
            if self._is_challenge_hub(img):
                self.ctx.tap_point("nav", "campaign", money_check=False, settle=1.0)
                sleep(0.8)
                continue
            self.ctx.tap_point("events", "dismiss_rewards", money_check=False, settle=0.5)
            self.ctx.back(settle=0.5)
            sleep(0.5)

    def _combat_runner(self, spec: ChallengeEventSpec) -> CombatRunner:
        kwargs: dict = {
            "battle_timeout": spec.battle_timeout,
            "dodge": False,
        }
        if spec.combat == "survival":
            kwargs["survival_only"] = True
        elif spec.combat == "skills_only":
            kwargs["skills_only"] = True
        elif spec.combat == "afk":
            kwargs["afk_only"] = True
        return CombatRunner(self.ctx, **kwargs)

    def _run_combat(self, runner: CombatRunner, spec: ChallengeEventSpec) -> bool:
        result, verified = runner.run_until_end_verified()
        log.info("    resultado: %s (verificado=%s)", result, verified)
        if not verified:
            return False
        if result == "timeout":
            return False
        if not runner.collect_event_end():
            log.warning("    post-run no cerrado")
            return False
        return True

    def _start_pixel(self, start_key: str) -> tuple[int, int]:
        try:
            p = self.ctx.coords.point("events", start_key)
            return p.y, p.x
        except ValueError:
            return 1264, 450

    def _is_challenge_hub(self, screen) -> bool:
        b, g, r = screen[1380, 450]
        return int(g) > 150 and (int(b) > 200 or int(r) > 200)

    def _is_popup(self, screen, spec: ChallengeEventSpec) -> bool:
        if is_lobby(screen):
            return False
        sy, sx = self._start_pixel(spec.start_key)
        b, g, r = screen[sy, sx]
        return int(r) > 200 and int(g) > 150

    def _tap_event(self, key: str, *, settle: float = 1.0) -> bool:
        try:
            self.ctx.tap_point("events", key, money_check=False, settle=settle)
            return True
        except ValueError as exc:
            log.warning("  coord events.%s sin calibrar: %s", key, exc)
            return False

    def _open_popup(self, spec: ChallengeEventSpec) -> bool:
        if self._is_popup(self.ctx.device.screenshot(), spec):
            return True
        if not self._ensure_events_hub():
            return False
        if not self._tap_event("tab_challenge", settle=1.0):
            return False
        sleep(0.4)
        if spec.scroll_before_open:
            self.ctx.swipe(450, 900, 450, 450, 450)
            sleep(0.5)
        if not self._tap_event(spec.banner_key, settle=1.2):
            return False
        sleep(0.8)
        return self._is_popup(self.ctx.device.screenshot(), spec)

    def _ensure_events_hub(self) -> bool:
        img = self.ctx.device.screenshot()
        if any(self._subtab(img, x) for x in (180, 450, 680)):
            return True
        try:
            self.ctx.tap_point("nav", "campaign", money_check=False, settle=1.0)
        except ValueError:
            pass
        sleep(0.6)
        try:
            self.ctx.tap_point("nav", "events", money_check=False, settle=1.5)
        except ValueError:
            return False
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            img = self.ctx.device.screenshot()
            if any(self._subtab(img, x) for x in (180, 450, 680)):
                return True
            sleep(0.45)
        return any(self._subtab(self.ctx.device.screenshot(), x) for x in (180, 450, 680))

    def _subtab(self, screen, x: int) -> bool:
        b, g, r = screen[1380, x]
        return int(g) > 150 and (int(b) > 200 or int(r) > 200)

    def _start_run(self, spec: ChallengeEventSpec) -> bool:
        if not self._is_popup(self.ctx.device.screenshot(), spec):
            return False
        if not self._tap_event(spec.start_key, settle=1.2):
            return False
        sleep(1.5)
        return self.ctx.current_screen() in {
            ScreenId.BATTLE,
            ScreenId.SKILL_SELECT,
            ScreenId.ROULETTE,
            ScreenId.DEVIL_DEAL,
        }
