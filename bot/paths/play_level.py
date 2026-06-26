"""Play path: play N games of a level (default 50).

Flow: lobby -> level selection -> enter ->
combat loop (dodge with swipes + choose skills) -> end of run ->
collect rewards -> return to lobby -> repeat.
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path
from types import TracebackType

import cv2
import numpy as np

from .. import screens, vision
from ..device import ROOT, sleep
from ..failsafes import (
    BattleTimeout,
    PathAborted,
    StopRequested,
    StuckDetector,
    UnknownScreenWatchdog,
)
from ..log import dump_screen, get_logger
from ..screens import ScreenId, is_lobby
from ..skills import SkillPicker
from .base import BotContext

log = get_logger("play")

LEVEL50_TEMPLATE = "anchors/level50.png"
LEVEL_TITLE_THRESHOLD = 0.80
PLAY_RUN_LOCK = ROOT / "logs" / "play_level.lock"
FIELD_ROULETTE_REGION = (420, 380, 320, 380)
FIELD_PLAYER_ANCHOR = (450, 820)
JOYSTICK_RADIUS = 330
ROULETTE_GRAB_MAX_ATTEMPTS = 3

_IN_COMBAT_SCREENS = frozenset(
    {
        ScreenId.BATTLE,
        ScreenId.SKILL_SELECT,
        ScreenId.ROULETTE,
        ScreenId.DEVIL_DEAL,
    }
)


class PlayRunLock:
    def __init__(self, path: Path = PLAY_RUN_LOCK) -> None:
        self.path = path
        self._fh = None

    def __enter__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._fh.close()
            self._fh = None
            raise PathAborted("Another farm/play is already running; not starting another") from exc
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(f"pid={os.getpid()} started={time.time():.0f}\n")
        self._fh.flush()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


class PlayLevelPath:
    def __init__(
        self,
        ctx: BotContext,
        level: int = 50,
        games: int | None = 1,
        battle_timeout: float = 200.0,
        max_games: int = 40,
        start_timeout: float = 40.0,
        forever: bool = False,
        energy_wait_s: float = 3600.0,
        dodge: bool = False,
        skills_only: bool = False,
        afk_only: bool = False,
        circle_move: bool | None = None,
        survival_only: bool = False,
    ) -> None:
        self.ctx = ctx
        self.level = level
        self.dodge = dodge
        self.skills_only = skills_only
        self.afk_only = afk_only
        self.survival_only = survival_only
        self.circle_move = survival_only or afk_only if circle_move is None else circle_move
        self._saw_battle = False
        # games=None -> play until energy is exhausted (farm mode).
        self.games = games
        self.until_no_energy = games is None
        self.battle_timeout = battle_timeout
        self.max_games = max_games
        self.start_timeout = start_timeout
        # forever -> when out of energy, wait and retry indefinitely.
        self.forever = forever
        self.energy_wait_s = energy_wait_s
        self.picker = SkillPicker()
        if self.until_no_energy:
            from ..run_end_dismiss import configure_farm_ctx

            configure_farm_ctx(ctx)

    def run(self) -> int:
        with PlayRunLock():
            return self._run_locked()

    def _run_locked(self) -> int:
        won = 0
        played = 0
        n = 0
        while True:
            if not self.forever:
                if not self.until_no_energy and n >= (self.games or 0):
                    break
                if self.until_no_energy and n >= self.max_games:
                    log.warning("Safety cap of %d games reached; stopping.", self.max_games)
                    break

            self.ctx.kill.check()
            if self.forever:
                label = f"{n + 1} (infinite)"
            elif self.until_no_energy:
                label = f"{n + 1} (energy farm)"
            else:
                label = f"{n + 1}/{self.games}"
            log.info("=== Game %s (level %d) ===", label, self.level)

            try:
                from ..run_end_dismiss import is_post_run_overlay

                sid = self.ctx.current_screen()
                screen = self.ctx.device.screenshot()
                in_combat = sid in (
                    ScreenId.ROULETTE,
                    ScreenId.BATTLE,
                    ScreenId.SKILL_SELECT,
                    ScreenId.DEVIL_DEAL,
                )
                at_run_end = sid in (ScreenId.VICTORY, ScreenId.DEFEAT) or is_post_run_overlay(screen)

                if at_run_end:
                    if sid not in (ScreenId.VICTORY, ScreenId.DEFEAT):
                        log.info("Reconnect: post-run active (%s); collecting and restarting.", sid.value)
                    else:
                        log.info("Reconnect: game already finished (%s); collecting and restarting.", sid.value)
                    self._collect_run_end()
                    continue

                if in_combat and not is_post_run_overlay(screen):
                    log.info("Reconnecting to a game in progress (%s)", sid.value)
                else:
                    if not self._enter_level():
                        if self._resume_active_run_after_start_failure():
                            continue
                        self._abort_start()
                        if self.forever:
                            log.info(
                                "Out of energy or level 50 not confirmed; waiting %.0f min and retrying.",
                                self.energy_wait_s / 60.0,
                            )
                            self._interruptible_sleep(self.energy_wait_s)
                            continue
                        log.info("Could not start game (out of energy or level unavailable). Stopping.")
                        break

                result = self._fight()
                log.info("Result: %s", result)
                if result == "victory":
                    won += 1
                if not self._collect_run_end():
                    sid = self.ctx.current_screen()
                    from ..run_end_dismiss import is_challenge_ended_screen

                    if sid in _IN_COMBAT_SCREENS and not is_challenge_ended_screen(
                        self.ctx.device.screenshot()
                    ):
                        log.warning("False end of game (%s); resuming combat", sid.value)
                        if result == "victory":
                            won -= 1
                        result = self._fight()
                        log.info("Result (resumed): %s", result)
                        if result == "victory":
                            won += 1
                        self._collect_run_end()
                played += 1
            except StopRequested:
                raise
            except (PathAborted, ValueError, KeyError) as exc:
                log.error("Game aborted: %s", exc)
                dump_screen(self.ctx.device, "play_aborted")
                self.ctx.return_to_lobby()
            n += 1

        log.info("Finished: %d game(s) played, %d victory(ies).", played, won)
        return won

    def _interruptible_sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.ctx.kill.check()
            sleep(min(5.0, max(0.1, end - time.time())))

    def _enter_level(self) -> bool:
        """Ensure level 50 is selected, press Start, and confirm combat.
        Never starts if level 50 cannot be confirmed (avoids playing another level)."""
        if self.ctx.current_screen() != ScreenId.LOBBY:
            if not self.ctx.return_to_lobby():
                log.warning("Lobby not confirmed before entering level")
                return False

        self._ensure_campaign_tab()
        if not self._ensure_level_50():
            log.warning("Could not confirm level 50; not pressing Start.")
            return False

        self.ctx.tap_point("lobby", "campaign_start", money_check=True, settle=0.0)
        return self._wait_combat_start()

    def _ensure_campaign_tab(self) -> None:
        try:
            self.ctx.tap_point("nav", "campaign", money_check=False, settle=0.8)
        except (KeyError, ValueError) as exc:
            log.warning("Could not tap nav.campaign before farm/play: %s", exc)

    def _level_50_visible(self) -> bool:
        try:
            return vision.matches(
                self.ctx.device.screenshot(), LEVEL50_TEMPLATE, threshold=LEVEL_TITLE_THRESHOLD
            )
        except FileNotFoundError:
            log.warning("Missing templates/%s; cannot verify level 50.", LEVEL50_TEMPLATE)
            return False

    def _ensure_level_50(self) -> bool:
        """Verify level 50 is centered. If not, navigate based on the current floor."""
        if self.ctx.current_screen() != ScreenId.LOBBY:
            log.warning("Not searching for level %d: current screen is not lobby/campaign", self.level)
            return False
        if self._level_50_visible():
            return True
        log.info("Level 50 not visible; navigating campaign map...")

        current = self._read_campaign_floor()
        if current is not None:
            log.info("Current map floor: %d (target %d)", current, self.level)
            if current == self.level:
                return self._fine_tune_level_50()
            if current < self.level:
                return self._scroll_toward_level(direction="up")
            return self._scroll_toward_level(direction="down")

        log.info("Floor not readable; scrolling up from current position...")
        if self._scroll_toward_level(direction="up"):
            return True
        log.info("Not found scrolling up; scrolling down from current position...")
        if self._scroll_toward_level(direction="down"):
            return True

        log.info("Full rescan from floor 1...")
        self._scroll_to_lowest_floor()
        return self._scroll_toward_level(direction="up")

    def _read_campaign_floor(self) -> int | None:
        try:
            region = self.ctx.coords.region("lobby", "campaign_floor_badge")
            if region[2] <= 0 or region[3] <= 0:
                region = vision.DEFAULT_CAMPAIGN_FLOOR_BADGE
        except (KeyError, ValueError):
            region = vision.DEFAULT_CAMPAIGN_FLOOR_BADGE
        return vision.read_campaign_floor_badge(self.ctx.device.screenshot(), region)

    def _fine_tune_level_50(self, max_nudges: int = 4) -> bool:
        """Badge says 50 but title does not match; short nudge in both directions."""
        for _ in range(max_nudges):
            if self._level_50_visible():
                return True
            self._swipe_higher_floor()
            sleep(0.25)
        for _ in range(max_nudges):
            if self._level_50_visible():
                return True
            self._swipe_lower_floor()
            sleep(0.25)
        ok = self._level_50_visible()
        if not ok:
            log.warning("Badge on floor %d but level 50 title not confirmed", self.level)
        return ok

    def _swipe_higher_floor(self) -> None:
        """Raise floor number (49 -> 50)."""
        self.ctx.device.swipe(450, 550, 450, 950, 600)

    def _swipe_lower_floor(self) -> None:
        """Lower floor number (50 -> 49)."""
        self.ctx.device.swipe(450, 950, 450, 550, 600)

    def _scroll_to_lowest_floor(self, max_swipes: int = 90) -> None:
        """Swipe until floor 1 (bottom of map)."""
        prev = None
        for _ in range(max_swipes):
            self.ctx.kill.check()
            screen = self.ctx.device.screenshot()
            if prev is not None and not vision.screen_changed(prev, screen, 0.008):
                log.info("Campaign map bottom reached (floor 1)")
                return
            prev = screen
            self._swipe_lower_floor()
            sleep(0.25)
        log.warning("Map bottom not detected after %d swipes", max_swipes)

    def _scroll_toward_level(self, direction: str, max_swipes: int = 70) -> bool:
        swipe = self._swipe_higher_floor if direction == "up" else self._swipe_lower_floor
        label = "scrolling up" if direction == "up" else "scrolling down"
        log.info("Searching for level %d (%s)...", self.level, label)
        stuck_reads = 0
        prev = None
        for _ in range(max_swipes):
            self.ctx.kill.check()
            if self._level_50_visible():
                log.info("Level %d located", self.level)
                return True
            swipe()
            sleep(0.3)
            screen = self.ctx.device.screenshot()
            if prev is not None and not vision.screen_changed(prev, screen, 0.008):
                stuck_reads += 1
                if stuck_reads >= 2:
                    log.info("Map edge reached (%s)", label)
                    return self._level_50_visible()
            else:
                stuck_reads = 0
            prev = screen
        ok = self._level_50_visible()
        if not ok:
            log.warning("Could not locate level %d after %d swipes (%s)", self.level, max_swipes, label)
        return ok

    def _scroll_to_bottom(self, max_swipes: int = 90) -> None:
        self._scroll_to_lowest_floor(max_swipes=max_swipes)

    def _scroll_until_level_50(self, max_swipes: int = 70) -> bool:
        return self._scroll_toward_level(direction="up", max_swipes=max_swipes)

    def _wait_combat_start(self) -> bool:
        """Confirm combat start. If it does not appear within start_timeout, assume
        entry failed (out of energy or purchase popup)."""
        deadline = time.time() + self.start_timeout
        popup_reads = 0
        while time.time() < deadline:
            self.ctx.kill.check()
            sid = self.ctx.current_screen()
            if sid in (
                ScreenId.BATTLE,
                ScreenId.ROULETTE,
                ScreenId.SKILL_SELECT,
                ScreenId.DEVIL_DEAL,
            ):
                log.info("Combat started (%s)", sid.value)
                return True
            if sid == ScreenId.POPUP:
                popup_reads += 1
                if popup_reads >= 2:
                    log.info("Popup on level start; closing without purchase and retrying later")
                    self._dismiss_start_blocker()
                    return False
            else:
                popup_reads = 0
            sleep(0.25)
        log.info("Combat start not detected within %.0fs", self.start_timeout)
        return False

    def _dismiss_start_blocker(self) -> None:
        self.ctx.back(settle=1.0)
        self.ctx.return_to_lobby()

    def _abort_start(self) -> None:
        """Close any popup (e.g. energy purchase) without spending and return to lobby.
        Never confirms purchases: back / close only."""
        self._dismiss_start_blocker()

    def _resume_active_run_after_start_failure(self) -> bool:
        from ..run_end_dismiss import is_post_run_overlay

        screen = self.ctx.device.screenshot()
        sid = screens.identify_combat(screen)
        if sid in _IN_COMBAT_SCREENS and not is_post_run_overlay(screen):
            log.warning(
                "Could not prepare lobby, but active run detected (%s); resuming combat.",
                sid.value,
            )
            result = self._fight()
            log.info("Result (resumed): %s", result)
            self._collect_run_end()
            return True
        if is_post_run_overlay(screen):
            log.warning("Could not prepare lobby, but post-run detected; collecting and continuing.")
            self._collect_run_end()
            return True
        return False

    def _fight(self) -> str:
        if self.survival_only:
            return self._fight_survival_only()
        if self.afk_only:
            return self._fight_afk_only()
        if self.skills_only:
            return self._fight_skills_only()
        return self._fight_standard()

    def fight_verified(self) -> tuple[str, bool]:
        result = self._fight()
        verified = self._saw_battle and result in ("victory", "defeat")
        return result, verified

    def _fight_survival_only(self) -> str:
        from ..combat_prompts import event_challenge_end, find_reject_button

        timeout = BattleTimeout(self.battle_timeout)
        end_streak = 0
        circle_phase = 0

        while True:
            self.ctx.kill.check()
            if timeout.expired():
                log.warning("BattleTimeout (%.0fs) reached", self.battle_timeout)
                return "timeout"

            screen = self.ctx.device.screenshot()

            if find_reject_button(screen) is not None:
                self._handle_pact_reject(screen)
                end_streak = 0
                continue

            sid = screens.identify_combat(screen)

            if sid == ScreenId.BATTLE:
                self._saw_battle = True

            if sid == ScreenId.SKILL_SELECT:
                self._pick_skill(screen)
                end_streak = 0
                continue
            if sid == ScreenId.DEVIL_DEAL:
                self._handle_devil_deal()
                end_streak = 0
                continue
            if sid == ScreenId.VICTORY:
                return "victory"
            if sid == ScreenId.DEFEAT:
                return "defeat"
            if sid == ScreenId.ROULETTE:
                self._handle_roulette()
                end_streak = 0
                continue
            if sid == ScreenId.BATTLE:
                self._circle_move(circle_phase)
                circle_phase += 1
                if event_challenge_end(screen):
                    end_streak += 1
                    if end_streak >= 2:
                        return "defeat"
                else:
                    end_streak = 0
                sleep(0.65)
                continue

            if event_challenge_end(screen):
                end_streak += 1
                if end_streak >= 2:
                    return "defeat"
            else:
                end_streak = 0

            sleep(0.5)

    def _fight_afk_only(self) -> str:
        """Dungeon AFK (Abyssal Tide): wait in combat; pick skill on level-up."""
        from ..combat_prompts import event_challenge_end, find_reject_button

        timeout = BattleTimeout(self.battle_timeout)
        end_streak = 0
        circle_phase = 0

        while True:
            self.ctx.kill.check()
            if timeout.expired():
                log.warning("BattleTimeout (%.0fs) reached", self.battle_timeout)
                return "timeout"

            screen = self.ctx.device.screenshot()

            if find_reject_button(screen) is not None:
                self._handle_pact_reject(screen)
                end_streak = 0
                continue

            sid = screens.identify_combat(screen)

            if sid == ScreenId.SKILL_SELECT:
                self._pick_skill(screen)
                end_streak = 0
                continue
            if sid == ScreenId.DEVIL_DEAL:
                self._handle_devil_deal()
                end_streak = 0
                continue
            if sid == ScreenId.VICTORY:
                return "victory"
            if sid == ScreenId.DEFEAT:
                return "defeat"
            if sid == ScreenId.ROULETTE:
                self._handle_roulette()
                end_streak = 0
                continue
            if sid == ScreenId.BATTLE:
                self._saw_battle = True
                if self.circle_move:
                    self._circle_move(circle_phase)
                    circle_phase += 1
                if event_challenge_end(screen):
                    end_streak += 1
                    if end_streak >= 2:
                        return "victory"
                else:
                    end_streak = 0
                sleep(0.75)
                continue

            if event_challenge_end(screen):
                end_streak += 1
                if end_streak >= 2:
                    return "victory"
            else:
                end_streak = 0

            sleep(0.5)

    def _circle_move(self, phase: int) -> None:
        try:
            origin = self.ctx.coords.point("battle", "grab_up_from")
            ax, ay = origin.x, origin.y
        except ValueError:
            ax, ay = 450, 1250
        angle = (phase % 4) * (math.pi / 2)
        radius = min(JOYSTICK_RADIUS, 220)
        bx = int(ax + radius * math.cos(angle))
        by = int(ay + radius * math.sin(angle))
        self.ctx.swipe(ax, ay, bx, by, duration_ms=420, settle=0.05)

    def _fight_skills_only(self) -> str:
        """Shackled Jungle: pick skills only, idle between level-ups."""
        from ..combat_prompts import event_challenge_end, find_reject_button

        timeout = BattleTimeout(self.battle_timeout)
        end_streak = 0

        while True:
            self.ctx.kill.check()
            if timeout.expired():
                log.warning("BattleTimeout (%.0fs) reached", self.battle_timeout)
                return "timeout"

            screen = self.ctx.device.screenshot()

            if find_reject_button(screen) is not None:
                self._handle_pact_reject(screen)
                end_streak = 0
                continue

            sid = screens.identify_combat(screen)

            if sid == ScreenId.SKILL_SELECT:
                self._pick_skill_skills_only(screen)
                end_streak = 0
                continue
            if sid == ScreenId.DEVIL_DEAL:
                self._handle_devil_deal()
                end_streak = 0
                continue
            if sid == ScreenId.VICTORY:
                return "victory"
            if sid == ScreenId.DEFEAT:
                return "defeat"
            if sid == ScreenId.ROULETTE:
                self._handle_roulette()
                end_streak = 0
                continue
            if sid == ScreenId.BATTLE:
                if event_challenge_end(screen):
                    end_streak += 1
                    if end_streak >= 2:
                        return "defeat"
                else:
                    end_streak = 0
                sleep(0.5)
                continue

            if event_challenge_end(screen):
                end_streak += 1
                if end_streak >= 2:
                    return "defeat"
            else:
                end_streak = 0

            sleep(0.5)

    def _handle_pact_reject(self, screen) -> None:
        from ..combat_prompts import find_reject_button, scan_and_reject_coords

        coords = scan_and_reject_coords(screen) or find_reject_button(screen)
        if coords is None:
            return
        log.info("Pact / active item detected -> Reject @(%d,%d)", coords[0], coords[1])
        self.ctx.tap(coords[0], coords[1], money_check=False, settle=0.0)
        sleep(0.6)
        self.ctx.wait_until_not(ScreenId.DEVIL_DEAL, timeout=2.0, interval=0.25)

    def _pick_skill_skills_only(self, screen) -> None:
        from ..combat_prompts import find_reject_button

        if find_reject_button(screen) is not None:
            self._handle_pact_reject(screen)
            return
        self._pick_skill(screen)

    def _fight_standard(self) -> str:
        timeout = BattleTimeout(self.battle_timeout)
        unknown = UnknownScreenWatchdog(patience=18.0)
        dodge_down = True
        idle_taps = 0
        roulette_grab_attempts = 0
        roulette_done = False

        while True:
            self.ctx.kill.check()
            if timeout.expired():
                log.warning("BattleTimeout (%.0fs) reached", self.battle_timeout)
                return "timeout"

            screen = self.ctx.device.screenshot()
            sid = screens.identify_combat(screen)

            if sid == ScreenId.ROULETTE:
                unknown.reset()
                self._handle_roulette()
                roulette_done = True
                continue
            if sid == ScreenId.SKILL_SELECT:
                unknown.reset()
                self._pick_skill(screen)
                continue
            if sid == ScreenId.DEVIL_DEAL:
                unknown.reset()
                self._handle_devil_deal()
                continue
            if sid == ScreenId.VICTORY:
                return "victory"
            if sid == ScreenId.DEFEAT:
                return "defeat"
            if sid == ScreenId.BATTLE:
                from ..run_end_dismiss import is_post_run_context

                if is_post_run_context(screen):
                    sleep(0.6)
                    confirm = self.ctx.device.screenshot()
                    if is_post_run_context(confirm):
                        log.info("Post-run detected (confirmed in battle) -> end of game")
                        return "victory"
                    confirm_sid = screens.identify_combat(confirm)
                    if confirm_sid == ScreenId.VICTORY:
                        return "victory"
                    if confirm_sid == ScreenId.DEFEAT:
                        return "defeat"
                from ..combat_prompts import detect_pact_offer

                if detect_pact_offer(screen):
                    self._handle_pact_reject(screen)
                    continue
                unknown.reset()
                if (
                    not roulette_done
                    and roulette_grab_attempts < ROULETTE_GRAB_MAX_ATTEMPTS
                ):
                    roulette_grab_attempts += 1
                    if not self._grab_roulette(screen, attempt=roulette_grab_attempts):
                        continue
                    continue
                if self.dodge:
                    self._dodge(dodge_down)
                    dodge_down = not dodge_down
                else:
                    sleep(0.35)
                continue

            if sid == ScreenId.UNKNOWN:
                from ..run_end_dismiss import is_post_run_context

                if is_post_run_context(screen):
                    log.info("Post-run detected (unknown) -> end of game")
                    return "victory"
                if (
                    not roulette_done
                    and roulette_grab_attempts < ROULETTE_GRAB_MAX_ATTEMPTS
                ):
                    roulette_grab_attempts += 1
                    if not self._grab_roulette(screen, attempt=roulette_grab_attempts):
                        continue
                    unknown.reset()
                    continue
                if unknown.update(True):
                    log.warning("Prolonged unknown screen; attempting to advance/recover")
                    if self._looks_like_run_end():
                        return "ended"
                    idle_taps += 1
                    if idle_taps >= 3:
                        raise PathAborted("Persistent unknown screen in combat")
                    unknown.reset()
                sleep(0.3)
                continue

            sleep(0.3)

    def _handle_roulette(self) -> None:
        """Roulette screen at start: press Start, spin and tap to skip/claim
        until combat resumes. Free (does not spend gems/money)."""
        log.info("Roulette detected: spin and claim")
        try:
            self.ctx.tap_point("roulette", "start", money_check=False, settle=0.0)
        except ValueError:
            self.ctx.tap(450, 1333, money_check=False, settle=0.0)
        sleep(0.2)
        try:
            skip = self.ctx.coords.point("roulette", "skip")
            sx, sy = skip.x, skip.y
        except ValueError:
            sx, sy = 450, 1000
        for _ in range(8):
            self.ctx.kill.check()
            if self.ctx.current_screen() != ScreenId.ROULETTE:
                log.info("Roulette closed; continuing combat")
                return
            self.ctx.tap(sx, sy, money_check=False, settle=0.0)
            if self.ctx.wait_until_not(ScreenId.ROULETTE, timeout=0.45, interval=0.15):
                log.info("Roulette closed; continuing combat")
                return
        log.warning("Roulette did not close after several taps; continuing anyway")

    def _handle_devil_deal(self) -> None:
        # By default we reject: the deal costs Max HP (death risk).
        # Configurable via skills.json -> "devil_deal": "sign".
        action = str(self.picker.config.get("devil_deal", "reject")).lower()
        key = "devil_sign" if action == "sign" else "devil_reject"
        log.info("Devil deal detected -> %s", key)
        self.ctx.tap_point("battle", key, money_check=False, settle=0.0)
        self.ctx.wait_until_not(ScreenId.DEVIL_DEAL, timeout=1.5, interval=0.2)

    def _pick_skill(self, screen) -> None:
        try:
            fallback = self.ctx.coords.regions("skill_select", "cards")
        except (KeyError, ValueError):
            fallback = None
        chosen = self.picker.choose(
            screen,
            fallback_regions=fallback,
            context="farm" if self.until_no_energy else "play",
        )
        log.info(
            "Choosing card %d (%s score=%d) -> (%d,%d)",
            chosen.index,
            chosen.skill_id,
            chosen.score,
            chosen.tap_x,
            chosen.tap_y,
        )
        self.ctx.tap(chosen.tap_x, chosen.tap_y, money_check=False, settle=0.0)
        self.ctx.wait_until_not(ScreenId.SKILL_SELECT, timeout=1.5, interval=0.2)

    def _field_roulette_target(self, screen) -> tuple[int, int] | None:
        x, y, w, h = FIELD_ROULETTE_REGION
        roi = vision.crop(screen, FIELD_ROULETTE_REGION)
        if roi.size == 0:
            return None
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        orange = cv2.inRange(hsv, np.array([5, 80, 80]), np.array([35, 255, 255]))
        green = cv2.inRange(hsv, np.array([35, 60, 70]), np.array([90, 255, 255]))
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(orange)
        best: tuple[float, int, int] | None = None
        for i in range(1, count):
            area = int(stats[i, cv2.CC_STAT_AREA])
            bx, by, bw, bh = (int(v) for v in stats[i, :4])
            if area < 1000 or not (45 <= bw <= 180 and 35 <= bh <= 170):
                continue
            pad = 24
            gx0, gy0 = max(0, bx - pad), max(0, by - pad)
            gx1, gy1 = min(w, bx + bw + pad), min(h, by + bh + pad)
            green_hits = int((green[gy0:gy1, gx0:gx1] > 0).sum())
            if green_hits < 250:
                continue
            cx = int(x + centroids[i][0])
            cy = int(y + centroids[i][1])
            if cx < 500 or cy > 720:
                continue
            score = green_hits + area * 0.1 - abs(cx - 560) * 0.4 - max(0, cy - 640) * 1.5
            if best is None or score > best[0]:
                best = (score, cx, cy)
        if best is None:
            return None
        return best[1], best[2]

    def _grab_roulette(self, screen, *, attempt: int) -> bool:
        """Move joystick toward the roulette visible on the field."""
        c = self.ctx.coords
        try:
            a = c.point("battle", "grab_up_from")
            ax, ay = a.x, a.y
        except ValueError:
            ax, ay = 450, 1250

        target = self._field_roulette_target(screen)
        if target is None:
            if attempt > 1:
                log.info("Field roulette not visible; not retrying initial movement")
                return False
            tx, ty = FIELD_PLAYER_ANCHOR[0], FIELD_PLAYER_ANCHOR[1] - 260
            src = "fallback"
        else:
            tx, ty = target
            src = "vision"

        dx = tx - FIELD_PLAYER_ANCHOR[0]
        dy = ty - FIELD_PLAYER_ANCHOR[1]
        norm = math.hypot(dx, dy)
        if norm < 1.0:
            return False
        bx = int(ax + dx / norm * JOYSTICK_RADIUS)
        by = int(ay + dy / norm * JOYSTICK_RADIUS)
        log.info(
            "Grabbing initial roulette (%s attempt %d): target=(%d,%d) swipe=(%d,%d)->(%d,%d)",
            src,
            attempt,
            tx,
            ty,
            ax,
            ay,
            bx,
            by,
        )
        self.ctx.swipe(ax, ay, bx, by, duration_ms=850, settle=0.15)
        return True

    def _dodge(self, down: bool) -> None:
        c = self.ctx.coords
        if down:
            a, b = c.point("battle", "dodge_down_from"), c.point("battle", "dodge_down_to")
        else:
            a, b = c.point("battle", "dodge_up_from"), c.point("battle", "dodge_up_to")
        self.ctx.swipe(a.x, a.y, b.x, b.y, duration_ms=220, settle=0.25)

    def _looks_like_run_end(self) -> bool:
        from ..run_end_dismiss import is_post_run_overlay

        screen = self.ctx.device.screenshot()
        sid = screens.identify(screen)
        return sid in (ScreenId.VICTORY, ScreenId.DEFEAT, ScreenId.LOBBY) or is_post_run_overlay(screen)

    def _collect_run_end(self) -> bool:
        """Close post-run result/rewards and confirm lobby."""
        from ..run_end_dismiss import dismiss_to_lobby, is_challenge_ended_screen

        if dismiss_to_lobby(self.ctx, max_rounds=4):
            log.info("Return to lobby confirmed")
            return True

        screen = self.ctx.device.screenshot()
        if is_challenge_ended_screen(screen):
            log.warning("Dismiss failed with post-run visible; retrying default tap")
            saved_tap = self.ctx.post_run_tap
            self.ctx.post_run_tap = None
            if dismiss_to_lobby(self.ctx, max_rounds=3):
                log.info("Return to lobby confirmed (alternate tap)")
                self.ctx.post_run_tap = saved_tap
                return True
            self.ctx.post_run_tap = saved_tap
            log.warning("Could not close post-run; forcing return_to_lobby")
            self.ctx.return_to_lobby()
            return is_lobby(self.ctx.device.screenshot())

        if self.ctx.current_screen() in _IN_COMBAT_SCREENS:
            log.warning("Dismiss aborted: game still in progress (false end?)")
            return False
        log.warning("Return to lobby not confirmed after game")
        self.ctx.return_to_lobby()
        return is_lobby(self.ctx.device.screenshot())

    def _collect_event_run_end(self, timeout: float = 90.0) -> bool:
        """Close victory/defeat and rewards without requiring lobby (Events/Dungeon)."""
        from ..combat_prompts import dismiss_shackled_challenge_end, event_challenge_end
        from ..run_end_dismiss import needs_post_run_dismiss

        combat = {
            ScreenId.BATTLE,
            ScreenId.SKILL_SELECT,
            ScreenId.ROULETTE,
            ScreenId.DEVIL_DEAL,
        }
        deadline = time.time() + timeout
        stable_out = 0
        while time.time() < deadline:
            self.ctx.kill.check()
            screen = self.ctx.device.screenshot()
            sid = self.ctx.current_screen()
            if needs_post_run_dismiss(screen):
                log.info("Event run end (post-run) -> tap empty")
                dismiss_shackled_challenge_end(self.ctx)
                stable_out = 0
                sleep(0.6)
                continue
            if sid in (ScreenId.VICTORY, ScreenId.DEFEAT):
                log.info("Event run end (%s) -> continue", sid.value)
                self.ctx.tap_point("run_end", "continue", money_check=True, settle=0.0)
                self.ctx.wait_until_not({ScreenId.VICTORY, ScreenId.DEFEAT}, timeout=2.5, interval=0.25)
                stable_out = 0
                continue
            if sid in combat:
                if event_challenge_end(screen):
                    log.warning(
                        "Post-run over %s; waiting for actual combat end",
                        sid.value,
                    )
                stable_out = 0
                sleep(0.4)
                continue
            stable_out += 1
            if stable_out >= 2:
                log.info("Event run finished (screen=%s)", sid.value)
                return True
            try:
                self.ctx.tap_point("events", "dismiss_rewards", money_check=False, settle=0.3)
            except ValueError:
                pass
            sleep(0.5)
        log.warning("Timeout closing event run")
        return False
