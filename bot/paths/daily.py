"""Daily path: main free-claims loop.

Main loop (no Friends):
  popups -> shop -> events -> great_value -> privilege -> messages ->
  guild -> hunt -> sidebar_events (island, angler, campaign_rout)

Coordinates in portrait space 900x1600 (same as screenshot and ADB tap).
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

import cv2

from .. import vision
from ..combat import CombatRunner
from ..daily_checks import DailyChecks, has_red_badge
from ..device import ROOT, sleep
from ..failsafes import MoneyBlocked, StopRequested
from ..log import get_logger
from ..screens import ScreenId, identify, identify_arena, identify_combat, is_lobby
from .base import BotContext

log = get_logger("daily")


@dataclass
class ArenaScreenState:
    screen: ScreenId
    arena: ScreenId | None
    on_lobby: bool
    rivals: dict[int, float | None] = field(default_factory=dict)

    @property
    def rivals_readable(self) -> bool:
        return any(v is not None for v in self.rivals.values())

MESSAGES_ICON = "anchors/messages_icon.png"
TASK_CLAIM_X = 780
DAILY_CLAIM_ROWS = (415, 515, 615, 715)
SIGN_IN_CLAIM_ROWS = (415, 515, 615, 715)
WEEKLY_CLAIM_ROWS = (415, 515, 615, 715, 815)
ACHIEVEMENT_CLAIM_ROWS = (415, 515, 615, 715, 815, 915)
MILESTONE_KEYS = ("milestone_20", "milestone_40", "milestone_60", "milestone_80", "milestone_100")
ARENA_FIGHTS = 2
ARENA_POWER_THRESHOLD_M = 5.0
ARENA_OPPONENT_INDEX = 3
ARENA_RIVAL_CHALLENGE_X = 800
ARENA_RIVAL_ROW_Y_FALLBACK: dict[int, int] = {
    1: 488,
    2: 688,
    3: 888,
    4: 1088,
    5: 1308,
}
ARENA_FALLBACK_OPPONENT_INDEX = 4
ARENA_REFRESH_BEFORE_FALLBACK = 6
ARENA_REFRESH_SETTLE_S = 2.5
ARENA_BATTLE_ABORT_S = 10.0
ARENA_RELOAD_AFTER_EXIT_S = 8.0
ARENA_VICTORY_POLL_S = 10.0
ARENA_VICTORY_TIMEOUT = 180.0
GOLD_CAVE_QUICK_RAIDS = 3
SHACKLED_JUNGLE_RUNS = 3
SHACKLED_JUNGLE_BATTLE_TIMEOUT = 600.0
ABYSSAL_TIDE_RUNS = 2
ABYSSAL_TIDE_BATTLE_TIMEOUT = 270.0
SHACKLED_COMBAT = frozenset({
    ScreenId.BATTLE,
    ScreenId.SKILL_SELECT,
    ScreenId.ROULETTE,
    ScreenId.DEVIL_DEAL,
})
DUNGEON_COMBAT = SHACKLED_COMBAT
DUNGEON_RESUME_CLAIMS = frozenset({"shackled_jungle", "abyssal_tide"})
ARENA_RESUME_CLAIMS = frozenset({"arena"})
RESUME_CLAIMS = DUNGEON_RESUME_CLAIMS | ARENA_RESUME_CLAIMS
RUNE_RUINS_KEYS_PER_X5 = 5
RUNE_RUINS_PICK_SLOTS = 9
# Legacy popup region where "Ongoing guild tech donations" (loading) appears.
LEGACY_LOADING_REGION = (150, 550, 600, 220)

MAIN_LOOP_ORDER: tuple[str, ...] = (
    "popups",
    "shop",
    "events",
    "great_value",
    "privilege",
    "messages",
    "guild",
    "hunt",
    "sidebar_events",
)

EXTRA_CLAIMS: tuple[str, ...] = (
    "gold_cave",
    "shackled_jungle",
    "abyssal_tide",
    "arena",
    "peak_arena",
    "rumble_ladder",
    "seal_battle",
    "monster_invasion",
    "magic_plant_defense",
    "task_center",
    "friends",
    "camp",
    "trophy",
    "rune_ruins",
    "island_treasure",
    "angler_bounty",
    "campaign_rout",
)

DEFAULT_CLAIM_ORDER = MAIN_LOOP_ORDER

CLAIM_ALIASES: dict[str, str] = {
    "popups": "popups",
    "shop": "shop",
    "events": "events",
    "gold_cave": "gold_cave",
    "shackled_jungle": "shackled_jungle",
    "shackled": "shackled_jungle",
    "jungle": "shackled_jungle",
    "abyssal_tide": "abyssal_tide",
    "abyssal": "abyssal_tide",
    "tide": "abyssal_tide",
    "arena": "arena",
    "peak_arena": "peak_arena",
    "great_value": "great_value",
    "great-value": "great_value",
    "privilege": "privilege",
    "privilege_card": "privilege",
    "messages": "messages",
    "mail": "messages",
    "guild": "guild",
    "hunt": "hunt",
    "sidebar_events": "sidebar_events",
    "sidebar": "sidebar_events",
    "island_treasure": "island_treasure",
    "island": "island_treasure",
    "angler_bounty": "angler_bounty",
    "angler": "angler_bounty",
    "eternal_lode": "angler_bounty",
    "campaign_rout": "campaign_rout",
    "campaign": "campaign_rout",
    "contract_mystling": "campaign_rout",
    "mystling": "campaign_rout",
    "task_center": "task_center",
    "tasks": "task_center",
    "friends": "friends",
    "camp": "camp",
    "trophy": "trophy",
    "rune_ruins": "rune_ruins",
    "rune": "rune_ruins",
    "ruins": "rune_ruins",
    "peak": "peak_arena",
    "rumble": "rumble_ladder",
    "rumble_ladder": "rumble_ladder",
    "seal": "seal_battle",
    "seal_battle": "seal_battle",
    "monster_invasion": "monster_invasion",
    "invasion": "monster_invasion",
    "magic_plant": "magic_plant_defense",
    "magic_plant_defense": "magic_plant_defense",
    "all": "all",
}


class DailyPath:
    def __init__(
        self,
        ctx: BotContext,
        *,
        force: bool = False,
        recover_emulator: bool = False,
        recover_ldplayer: bool | None = None,
        arena_fights: int | None = None,
        arena_max_power: float | None = None,
        arena_exit_early: bool = False,
        arena_confirm: bool = False,
        arena_confirm_wait: float | None = None,
        arena_battle_abort_s: float | None = None,
        arena_reload_after_exit_s: float | None = None,
        rune_ruins_keys: int | None = None,
        shackled_jungle_runs: int | None = None,
        abyssal_tide_runs: int | None = None,
    ) -> None:
        self.ctx = ctx
        self.checks = DailyChecks(force=force)
        self.combat = CombatRunner(ctx, battle_timeout=180.0, dodge=False)
        if recover_ldplayer is not None:
            recover_emulator = recover_ldplayer
        self.recover_emulator = recover_emulator
        self._emulator_recovery_used = False
        self.arena_fights = arena_fights if arena_fights is not None else ARENA_FIGHTS
        self.arena_max_power = (
            arena_max_power if arena_max_power is not None else ARENA_POWER_THRESHOLD_M
        )
        self.arena_exit_early = arena_exit_early
        self.arena_confirm = arena_confirm
        self.arena_confirm_wait = arena_confirm_wait
        self.arena_battle_abort_s = (
            arena_battle_abort_s if arena_battle_abort_s is not None else ARENA_BATTLE_ABORT_S
        )
        self.arena_reload_after_exit_s = (
            arena_reload_after_exit_s
            if arena_reload_after_exit_s is not None
            else ARENA_RELOAD_AFTER_EXIT_S
        )
        self.rune_ruins_keys = rune_ruins_keys
        self.shackled_jungle_runs = (
            shackled_jungle_runs if shackled_jungle_runs is not None else SHACKLED_JUNGLE_RUNS
        )
        self.abyssal_tide_runs = (
            abyssal_tide_runs if abyssal_tide_runs is not None else ABYSSAL_TIDE_RUNS
        )

    @classmethod
    def available_claims(cls) -> tuple[str, ...]:
        return MAIN_LOOP_ORDER + EXTRA_CLAIMS

    @classmethod
    def resolve_claims(cls, names: list[str] | None) -> list[str]:
        if not names:
            return list(MAIN_LOOP_ORDER)
        resolved: list[str] = []
        for raw in names:
            key = CLAIM_ALIASES.get(raw.lower())
            if key is None:
                valid = ", ".join(sorted({k for k in CLAIM_ALIASES if k != "all"}))
                raise ValueError(f"Unknown claim: {raw!r}. Valid: {valid}")
            if key == "all":
                return list(MAIN_LOOP_ORDER)
            if key not in resolved:
                resolved.append(key)
        return resolved

    def _skip_lobby_for_abyssal(self) -> bool:
        return (
            self._is_abyssal_tide_popup()
            or self._is_events_hub()
        )

    def _skip_lobby_for_shackled(self) -> bool:
        return (
            self._is_shackled_jungle_popup()
            or self._is_events_hub()
        )

    def _skip_lobby_for_dungeon(self, claim: str) -> bool:
        if claim == "shackled_jungle":
            return self._skip_lobby_for_shackled()
        if claim == "abyssal_tide":
            return self._skip_lobby_for_abyssal()
        return False

    def _skip_lobby_for_arena(self) -> bool:
        screen = self.ctx.device.screenshot()
        return (
            self._is_arena_opponents_popup(screen)
            or self._is_arena_personal_info_overlay(screen)
            or self._is_arena_leaderboard(screen)
            or self._is_events_hub(screen)
        )

    def _skip_lobby_for_claim(self, claim: str) -> bool:
        if claim == "arena":
            return self._skip_lobby_for_arena()
        return self._skip_lobby_for_dungeon(claim)

    def _solo_claim_resume(self, selected: list[str]) -> bool:
        return (
            len(selected) == 1
            and selected[0] in RESUME_CLAIMS
            and self._skip_lobby_for_claim(selected[0])
        )

    def _solo_dungeon_resume(self, selected: list[str]) -> bool:
        return self._solo_claim_resume(selected)

    def run(self, claims: list[str] | None = None) -> None:
        selected = self.resolve_claims(claims)
        single_claim = len(selected) == 1
        lobby_ready = False
        if not self._solo_claim_resume(selected):
            self.ensure_campaign_lobby()
            lobby_ready = True
        log.info("Claims to run: %s", ", ".join(selected))
        for name in selected:
            if not self.checks.should_run(name):
                continue
            resume_ready = name in RESUME_CLAIMS and self._skip_lobby_for_claim(name)
            if not resume_ready and not (single_claim and lobby_ready):
                self.ensure_campaign_lobby()
            handler = self._claim_handler(name)
            try:
                handler()
            except StopRequested:
                raise
            except Exception as exc:  # noqa: BLE001
                log.error("Claim failed (%s): %s", name, exc)
        log.info("Claims completed (%d).", len(selected))

    def run_one(self, name: str) -> None:
        self.run([name])

    def mark_verified(self, name: str) -> None:
        self.checks.mark_verified(name)

    def ensure_campaign_lobby(self) -> bool:
        from ..navigation import ensure_campaign_lobby as nav_ensure_campaign_lobby

        return nav_ensure_campaign_lobby(self.ctx, exit_combat=True)

    def _claim_handler(self, name: str):
        handlers = {
            "popups": self.claim_popups,
            "shop": self.claim_shop,
            "events": self.claim_events,
            "gold_cave": self.claim_gold_cave,
            "shackled_jungle": self.claim_shackled_jungle,
            "abyssal_tide": self.claim_abyssal_tide,
            "arena": self.claim_arena,
            "peak_arena": self.claim_peak_arena,
            "rumble_ladder": self.claim_rumble_ladder,
            "seal_battle": self.claim_seal_battle,
            "monster_invasion": self.claim_monster_invasion,
            "magic_plant_defense": self.claim_magic_plant_defense,
            "great_value": self.claim_great_value,
            "privilege": self.claim_privilege,
            "messages": self.claim_messages,
            "guild": self.claim_guild,
            "hunt": self.claim_hunt,
            "sidebar_events": self.claim_sidebar_events,
            "task_center": self.claim_task_center,
            "friends": self.claim_friends,
            "island_treasure": self.claim_island_treasure,
            "camp": self.claim_camp,
            "angler_bounty": self.claim_angler_bounty,
            "campaign_rout": self.claim_campaign_rout,
            "trophy": self.claim_trophy,
            "rune_ruins": self.claim_rune_ruins,
        }
        return handlers[name]

    def _opt(self, section: str, key: str, settle: float = 0.8, money_check: bool = True) -> bool:
        try:
            self.ctx.tap_point(section, key, money_check=money_check, settle=settle)
            return True
        except ValueError as exc:
            log.warning("Step skipped %s.%s: %s", section, key, exc)
            return False
        except MoneyBlocked as exc:
            log.warning("Step blocked by MoneyGuard %s.%s: %s", section, key, exc)
            return False

    def _tap(self, x: int, y: int, *, settle: float = 0.6, money_check: bool = False) -> None:
        self.ctx.tap(x, y, money_check=money_check, settle=settle)

    def _dismiss_reward_popup(self, times: int = 1) -> None:
        for _ in range(times):
            self._opt("task_center", "dismiss_reward", settle=0.4, money_check=False)

    def _back(self) -> None:
        self._opt("menu", "back", settle=0.5, money_check=False)

    def _go_campaign(self) -> None:
        self._opt("nav", "campaign", settle=0.8, money_check=False)

    def _lobby_badge(self, section: str, key: str) -> bool:
        try:
            p = self.ctx.coords.point(section, key)
        except (KeyError, ValueError):
            return True
        screen = self.ctx.device.screenshot()
        if section == "lobby" and key in {"privilege_card", "messages", "great_value"}:
            return any(
                has_red_badge(
                    screen,
                    p.x,
                    p.y,
                    radius=radius,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    min_pixels=min_pixels,
                )
                for offset_x, offset_y, radius, min_pixels in (
                    (16, -16, 20, 55),
                    (26, -18, 28, 35),
                    (36, -22, 32, 25),
                )
            )
        return has_red_badge(screen, p.x, p.y)

    def _shop_tab_badge(self, tab_key: str) -> bool:
        try:
            p = self.ctx.coords.point("shop", tab_key)
        except (KeyError, ValueError):
            return False
        return has_red_badge(self.ctx.device.screenshot(), p.x, p.y)

    def _hunt_quick_available(self, key: str) -> bool:
        try:
            p = self.ctx.coords.point("hunt", f"{key}_badge")
        except (KeyError, ValueError):
            try:
                p = self.ctx.coords.point("hunt", key)
            except (KeyError, ValueError):
                return False
        screen = self.ctx.device.screenshot()
        return any(
            has_red_badge(
                screen,
                p.x,
                p.y,
                radius=radius,
                offset_x=offset_x,
                offset_y=offset_y,
                min_pixels=min_pixels,
            )
            for offset_x, offset_y, radius, min_pixels in (
                (16, -16, 22, 45),
                (28, -20, 28, 30),
                (40, -24, 34, 22),
                (0, 0, 26, 35),
            )
        )

    def _hunt_quick_chances(self, key: str) -> int | None:
        try:
            region = self.ctx.coords.region("hunt", f"{key}_chances")
        except (KeyError, ValueError):
            return None
        return vision.read_hunt_chances(self.ctx.device.screenshot(), region)

    def _claim_all_generic(self, section: str, key: str = "claim_all") -> None:
        if self._opt(section, key, settle=0.8, money_check=False):
            self._dismiss_reward_popup(2)

    def _tap_optional_reward(
        self,
        section: str,
        key: str,
        *,
        settle: float = 0.8,
        money_check: bool = True,
        dismiss_times: int = 1,
        dismiss_cb=None,
        change_threshold: float = 0.008,
    ) -> bool:
        before = self.ctx.device.screenshot()
        if not self._opt(section, key, settle=settle, money_check=money_check):
            return False
        if dismiss_cb is not None:
            dismiss_cb()
        elif dismiss_times:
            self._dismiss_reward_popup(dismiss_times)
        after = self.ctx.device.screenshot()
        changed = vision.screen_changed(before, after, threshold=change_threshold)
        if not changed:
            log.info("  No visible change after %s.%s; assuming unavailable", section, key)
        return changed

    def _exit_battle(self) -> None:
        self._opt("battle", "pause", settle=0.8, money_check=False)
        self._opt("battle", "exit_battle", settle=0.6, money_check=False)
        sleep(0.5)
        try:
            match = vision.find_template(self.ctx.device.screenshot(), "anchors/confirm_btn.png")
            if match.confidence >= 0.75:
                self.ctx.tap(match.cx, match.cy, money_check=False, settle=1.2)
                return
        except FileNotFoundError:
            pass
        self._opt("battle", "exit_confirm", settle=0.8, money_check=False)

    def _tap_claim_column(
        self,
        x: int = TASK_CLAIM_X,
        rows: tuple[int, ...] = DAILY_CLAIM_ROWS,
        settle: float = 0.5,
    ) -> None:
        for y in rows:
            self.ctx.tap(x, y, money_check=False, settle=settle)

    def _scroll_task_list(self) -> None:
        self.ctx.swipe(680, 780, 680, 980, duration_ms=350, settle=0.3)

    def _claim_task_rows(self, rows: tuple[int, ...], *, passes: int = 1) -> None:
        for i in range(passes):
            self._tap_claim_column(TASK_CLAIM_X, rows)
            self._dismiss_reward_popup(1)
            if i + 1 < passes:
                self._scroll_task_list()

    def _finish_claim(self, name: str) -> None:
        self.checks.mark_verified(name)

    # --- Claims del loop principal ---

    def claim_popups(self) -> None:
        log.info("-> Close initial popups")
        self._dismiss_reward_popup(1)
        self._opt("menu", "close_x", settle=0.5, money_check=False)
        self._finish_claim("popups")

    def claim_shop(self) -> None:
        log.info("-> Shop (Gear Chest, Limited Offer, Top Up)")
        if not self._opt("nav", "shop", settle=1.5):
            return

        had_work = self.checks.force or any(
            self._shop_tab_badge(key)
            for key in ("tab_gear_chest", "tab_limited_offer", "tab_top_up")
        )
        claimed_any = False

        if self._shop_tab_badge("tab_gear_chest") or self.checks.force:
            if self._opt("shop", "tab_gear_chest", settle=0.8, money_check=False):
                for key in ("gear_chest_blue_free", "gear_chest_violet_free"):
                    claimed_any |= self._tap_optional_reward("shop", key, settle=1.0, money_check=True, dismiss_times=2)

        if self._shop_tab_badge("tab_limited_offer") or self.checks.force:
            self._opt("shop", "tab_limited_offer", settle=0.8, money_check=False)
            for key in (
                "limited_offer_daily_free",
                "limited_offer_weekly_free",
                "limited_offer_monthly_free",
            ):
                claimed_any |= self._tap_optional_reward("shop", key, settle=0.8, money_check=True, dismiss_times=2)
                if not self.checks.force and not self._shop_tab_badge("tab_limited_offer"):
                    break

        if self._shop_tab_badge("tab_top_up") or self.checks.force:
            self._opt("shop", "tab_top_up", settle=0.8, money_check=False)
            self._opt("shop", "top_up_sub_gold", settle=0.8, money_check=False)
            for key in ("top_up_gold_free_1", "top_up_gold_free_2"):
                claimed_any |= self._tap_optional_reward("shop", key, settle=0.8, money_check=True, dismiss_times=2)

        self._go_campaign()
        if claimed_any or not had_work:
            self._finish_claim("shop")
        else:
            log.warning("Shop had badge but could not confirm any free; not marking verified")

    def claim_gold_cave(self) -> None:
        log.info("-> Events / Dungeon / Gold Cave")
        if not self._opt("nav", "events", settle=1.5):
            return
        self._events_gold_cave()
        self._go_campaign()
        self.checks.mark_verified("gold_cave")

    def claim_shackled_jungle(self) -> None:
        log.info("-> Events / Dungeon / Shackled Jungle")
        try:
            resume = self._is_shackled_combat_active()
            if resume:
                runs = self._events_shackled_jungle(resume=True)
            elif self._is_shackled_jungle_popup():
                runs = self._events_shackled_jungle(from_popup=True)
            else:
                runs = self._events_shackled_jungle()
            if runs > 0:
                self._finish_claim("shackled_jungle")
            else:
                log.warning("Shackled Jungle: 0 runs completed; not marking verified")
        finally:
            self._exit_shackled_jungle()

    def claim_abyssal_tide(self) -> None:
        log.info("-> Events / Dungeon / Abyssal Tide")
        try:
            resume = self._is_abyssal_combat_active()
            if resume:
                runs = self._events_abyssal_tide(resume=True)
            elif self._is_abyssal_tide_popup():
                runs = self._events_abyssal_tide(from_popup=True)
            else:
                runs = self._events_abyssal_tide()
            if runs > 0:
                self._finish_claim("abyssal_tide")
            else:
                log.warning("Abyssal Tide: 0 runs completed; not marking verified")
        finally:
            self._exit_abyssal_tide()

    def _events_subtab_highlighted(self, screen, x: int) -> bool:
        b, g, r = screen[1380, x]
        return int(g) > 150 and (int(b) > 200 or int(r) > 200)

    def _is_events_hub(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        if is_lobby(img):
            return False
        if self._is_shackled_jungle_popup_screen(img):
            return True
        if self._is_abyssal_tide_popup_screen(img):
            return True
        arena_sid = identify_arena(img)
        if arena_sid is not None:
            return True
        return any(self._events_subtab_highlighted(img, x) for x in (180, 450, 680))

    def _try_open_events_nav(self) -> bool:
        if self._is_shackled_jungle_popup() or self._is_abyssal_tide_popup():
            return True
        if self._is_events_hub():
            return True

        self._opt("nav", "campaign", settle=1.2, money_check=False)
        sleep(0.8)
        before = self.ctx.device.screenshot()
        if not self._opt("nav", "events", settle=1.5, money_check=False):
            return self._is_events_hub()

        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            after = self.ctx.device.screenshot()
            if self._is_events_hub(after):
                return True
            if vision.difference(before, after) > 0.02:
                sleep(0.45)
                continue
            sleep(0.45)

        after = self.ctx.device.screenshot()
        if self._is_events_hub(after):
            return True
        arena_sid = identify_arena(after)
        if arena_sid is not None:
            log.info("  Events: already in Arena (%s); continuing", arena_sid.value)
            return True
        if vision.difference(before, after) > 0.015:
            sid = self.ctx.current_screen()
            log.info(
                "  Events: screen changed (%s); continuing to Dungeon",
                sid.value,
            )
            return True
        log.warning(
            "  Events screen not confirmed (stuck on %s)",
            self.ctx.current_screen().value,
        )
        return False

    def _ensure_events_hub(self) -> bool:
        if (
            self._is_shackled_jungle_popup()
            or self._is_abyssal_tide_popup()
            or self._is_events_hub()
        ):
            return True
        return self._try_open_events_nav()

    def _is_shackled_jungle_popup_screen(self, screen) -> bool:
        from ..screens import identify_combat

        if is_lobby(screen):
            return False
        if identify_combat(screen) in DUNGEON_COMBAT:
            return False
        b, g, r = screen[1264, 450]
        if not (int(r) > 200 and int(g) > 150):
            return False
        if self._events_subtab_highlighted(screen, 680):
            return False
        return True

    def _is_shackled_jungle_popup(self) -> bool:
        return self._is_shackled_jungle_popup_screen(self.ctx.device.screenshot())

    def _dungeon_start_pixel(self, start_key: str) -> tuple[int, int]:
        try:
            p = self.ctx.coords.point("events", start_key)
            return p.y, p.x
        except ValueError:
            return 1264, 450

    def _dungeon_event_popup_screen(self, screen, start_key: str) -> bool:
        from ..screens import identify_combat

        if is_lobby(screen):
            return False
        if identify_combat(screen) in DUNGEON_COMBAT:
            return False
        if self._events_subtab_highlighted(screen, 680):
            return False
        sy, sx = self._dungeon_start_pixel(start_key)
        b, g, r = screen[sy, sx]
        if not (int(r) > 200 and int(g) > 150):
            return False
        return True

    def _is_abyssal_tide_popup_screen(self, screen) -> bool:
        if not self._dungeon_event_popup_screen(screen, "abyssal_tide_start"):
            return False
        # "Abyssal Tide" title top-left (Refresh on skill select does not have it)
        tb, tg, tr = screen[165, 250]
        return int(tb) > 200 and int(tg) < 130

    def _is_abyssal_tide_popup(self) -> bool:
        return self._is_abyssal_tide_popup_screen(self.ctx.device.screenshot())

    def claim_events(self) -> None:
        log.info("-> Events (Gold Cave + Arena + Peak Arena)")
        if not self._opt("nav", "events", settle=1.5):
            return

        self._events_gold_cave()
        self._run_arena_fights("arena", fights=self.arena_fights)
        self._run_arena_fights("peak_arena", fights=self.arena_fights)

        self._leave_arena_to_campaign()
        self._finish_claim("events")

    def _gold_cave_dismiss_rewards(self) -> None:
        self._opt("events", "gold_cave_dismiss_empty", settle=0.5, money_check=False)

    def _gold_cave_tap_quick_raid(self, *, taps: int = 1) -> None:
        for i in range(taps):
            self._opt("events", "gold_cave_quick_raid", settle=0.4 if i < taps - 1 else 0.8, money_check=False)
            if i < taps - 1:
                sleep(0.7)

    def _gold_cave_raid_cycle(self, *, quick_raid_taps: int) -> bool:
        before = self.ctx.device.screenshot()
        self._gold_cave_tap_quick_raid(taps=quick_raid_taps)
        sleep(2.0)
        if vision.difference(before, self.ctx.device.screenshot()) <= 0.015:
            return False
        log.info("    Rewards -> tap empty")
        self._gold_cave_dismiss_rewards()
        sleep(0.5)
        return True

    def _events_gold_cave(self) -> None:
        log.info("  Gold Cave (Dungeon, %d Quick Raids)", GOLD_CAVE_QUICK_RAIDS)
        self._opt("events", "tab_dungeon", settle=1.0, money_check=False)
        if not self._opt("events", "gold_cave_banner", settle=1.2, money_check=False):
            return

        if self._gold_cave_raid_cycle(quick_raid_taps=1):
            log.info("    Quick Raid 1/%d ok", GOLD_CAVE_QUICK_RAIDS)
        else:
            log.info("    Quick Raid 1 no rewards; stopping")
            self._opt("menu", "close_x", settle=0.6, money_check=False)
            return

        for n in range(2, GOLD_CAVE_QUICK_RAIDS + 1):
            log.info("    Quick Raid %d/%d (double tap: enable ticket + raid)", n, GOLD_CAVE_QUICK_RAIDS)
            if not self._gold_cave_raid_cycle(quick_raid_taps=2):
                log.info("    No more Quick Raids")
                break

        self._opt("menu", "close_x", settle=0.6, money_check=False)

    def _is_shackled_combat_active(self) -> bool:
        # Combat screen anchors are shared across dungeon modes; without popup evidence,
        # resuming a named dungeon can credit the wrong claim.
        return False

    def _open_shackled_jungle_popup(self) -> bool:
        if self._is_shackled_jungle_popup():
            return True
        if not self._ensure_events_hub():
            return False

        def try_banner() -> bool:
            before = self.ctx.device.screenshot()
            if not self._opt("events", "shackled_jungle_banner", settle=1.2, money_check=False):
                return False
            sleep(0.4)
            if self._is_shackled_jungle_popup():
                return True
            after = self.ctx.device.screenshot()
            if vision.difference(before, after) <= 0.015:
                return False
            return self._is_shackled_jungle_popup()

        self._opt("events", "tab_dungeon", settle=1.0, money_check=False)
        sleep(0.4)
        if try_banner():
            return True
        log.info("  Scroll Dungeon list toward Shackled Jungle")
        self.ctx.swipe(450, 900, 450, 450, 450)
        sleep(0.5)
        self._opt("events", "tab_dungeon", settle=0.5, money_check=False)
        sleep(0.3)
        return try_banner()

    def _shackled_jungle_dismiss_rewards(self) -> None:
        self._opt("events", "dismiss_rewards", settle=0.5, money_check=False)

    def _exit_shackled_jungle(self) -> None:
        from ..combat_prompts import dismiss_shackled_challenge_end, event_challenge_end
        from ..run_end_dismiss import needs_post_run_dismiss

        if is_lobby(self.ctx.device.screenshot()):
            return
        log.info("  Leaving Shackled Jungle -> campaign lobby")
        for _ in range(10):
            self.ctx.kill.check()
            img = self.ctx.device.screenshot()
            sid = self.ctx.current_screen()
            if is_lobby(img):
                log.info("  Campaign lobby reached")
                return
            if sid in DUNGEON_COMBAT:
                if needs_post_run_dismiss(img):
                    log.info("  Closing post-run Shackled Jungle")
                    dismiss_shackled_challenge_end(self.ctx)
                    sleep(0.8)
                elif self._resume_shackled_combat():
                    continue
                else:
                    sleep(0.5)
                continue
            if event_challenge_end(img) or needs_post_run_dismiss(img):
                log.info("  Closing Challenge has ended screen")
                dismiss_shackled_challenge_end(self.ctx)
                sleep(0.8)
                continue
            if self._is_shackled_jungle_popup_screen(img):
                log.info("  Back from Shackled Jungle popup")
                self._opt("menu", "back", settle=0.8, money_check=False)
                sleep(0.8)
                continue
            if self._is_events_hub(img):
                log.info("  Events -> Campaign")
                self._go_campaign()
                sleep(1.0)
                continue
            if sid in (ScreenId.VICTORY, ScreenId.DEFEAT):
                self._opt("run_end", "continue", settle=0.5, money_check=False)
                sleep(0.6)
                continue
            self._shackled_jungle_dismiss_rewards()
            self._opt("menu", "back", settle=0.5, money_check=False)
            self._go_campaign()
            sleep(0.8)
        if not is_lobby(self.ctx.device.screenshot()):
            log.warning("  Campaign lobby not confirmed after leaving Shackled Jungle")
            self.ensure_campaign_lobby()

    def _shackled_jungle_tap_start(self, *, taps: int = 1) -> None:
        for i in range(taps):
            self._opt(
                "events",
                "shackled_jungle_start",
                settle=0.4 if i < taps - 1 else 1.0,
                money_check=False,
            )
            if i < taps - 1:
                sleep(0.7)

    def _select_shackled_ad_entry(self) -> None:
        self._opt("events", "shackled_jungle_entry_ad", settle=0.6, money_check=False)

    def _start_shackled_jungle_run(self, *, use_ad_ticket: bool = False) -> bool:
        if not self._is_shackled_jungle_popup():
            log.warning("    Start ignored: not on Shackled Jungle popup")
            return False
        if use_ad_ticket:
            log.info("    ad ticket -> select entry + double Start")
            self._select_shackled_ad_entry()
            taps = 2
        else:
            log.info("    Start (ticket free)")
            taps = 1
        before = self.ctx.device.screenshot()
        self._shackled_jungle_tap_start(taps=taps)
        sleep(1.5)
        sid = self.ctx.current_screen()
        if sid in SHACKLED_COMBAT:
            return True
        after = self.ctx.device.screenshot()
        if vision.difference(before, after) <= 0.015:
            if not use_ad_ticket:
                log.info("    Start no response; retry with ad ticket + double Start")
                self._select_shackled_ad_entry()
                self._shackled_jungle_tap_start(taps=2)
                sleep(1.5)
                return self.ctx.current_screen() in SHACKLED_COMBAT
            return False
        return self.ctx.current_screen() in SHACKLED_COMBAT

    def _shackled_run_counted(self, result: str) -> bool:
        return result in ("victory", "defeat")

    def _run_one_shackled(self, dungeon_combat: CombatRunner) -> bool:
        result = dungeon_combat.run_until_end()
        log.info("    result: %s", result)
        if not self._shackled_run_counted(result):
            return False
        if not dungeon_combat.collect_event_end():
            log.warning("    Shackled post-run not closed")
            return False
        sleep(0.8)
        return True

    def _events_shackled_jungle(self, *, resume: bool = False, from_popup: bool = False) -> int:
        max_runs = self.shackled_jungle_runs
        log.info("  Shackled Jungle (up to %d attempts, skills only, no movement)", max_runs)

        dungeon_combat = CombatRunner(
            self.ctx,
            battle_timeout=SHACKLED_JUNGLE_BATTLE_TIMEOUT,
            dodge=False,
            skills_only=True,
        )

        completed = 0
        runs_left = max_runs
        self.ctx.hold_combat = True
        try:
            if resume or self._is_shackled_combat_active():
                log.info("    resuming ongoing combat")
                if self._run_one_shackled(dungeon_combat):
                    completed += 1
                runs_left -= 1
                if runs_left <= 0:
                    return completed

            if from_popup or self._is_shackled_jungle_popup():
                pass
            elif not self._open_shackled_jungle_popup():
                log.warning("  Could not open Shackled Jungle popup")
                return completed

            for n in range(runs_left):
                run_num = max_runs - runs_left + n + 1
                log.info("    run %d/%d", run_num, max_runs)
                if not self._start_shackled_jungle_run(use_ad_ticket=False):
                    log.info("    Start unavailable; stopping")
                    break
                if self._run_one_shackled(dungeon_combat):
                    completed += 1
                if n + 1 >= runs_left:
                    break
                sleep(0.5)
                if not self._is_shackled_jungle_popup() and not self._open_shackled_jungle_popup():
                    break
        finally:
            self.ctx.hold_combat = False

        return completed

    def _is_abyssal_combat_active(self) -> bool:
        # Combat screen anchors are shared across dungeon modes; without popup evidence,
        # resuming a named dungeon can credit the wrong claim.
        return False

    def _open_abyssal_tide_popup(self) -> bool:
        if self._is_abyssal_tide_popup():
            return True
        if not self._is_events_hub():
            self._try_open_events_nav()

        def try_banner() -> bool:
            before = self.ctx.device.screenshot()
            if not self._opt("events", "abyssal_tide_banner", settle=1.2, money_check=False):
                return False
            sleep(0.4)
            if self._is_abyssal_tide_popup():
                return True
            after = self.ctx.device.screenshot()
            if vision.difference(before, after) <= 0.015:
                return False
            return self._is_abyssal_tide_popup()

        self._opt("events", "tab_dungeon", settle=1.0, money_check=False)
        sleep(0.4)
        if try_banner():
            return True
        log.info("  Scroll Dungeon list toward Abyssal Tide")
        self.ctx.swipe(450, 900, 450, 450, 450)
        sleep(0.5)
        self._opt("events", "tab_dungeon", settle=0.5, money_check=False)
        sleep(0.3)
        if try_banner():
            return True
        self.ctx.swipe(450, 450, 450, 900, 450)
        sleep(0.5)
        return try_banner()

    def _resume_shackled_combat(self) -> bool:
        if self.ctx.current_screen() not in DUNGEON_COMBAT:
            return False
        log.info("  Resuming Shackled Jungle combat")
        runner = CombatRunner(
            self.ctx,
            battle_timeout=SHACKLED_JUNGLE_BATTLE_TIMEOUT,
            dodge=False,
            skills_only=True,
        )
        return self._run_one_shackled(runner)

    def _resume_abyssal_combat(self) -> bool:
        if self.ctx.current_screen() not in DUNGEON_COMBAT:
            return False
        log.info("  Resuming Abyssal Tide combat")
        runner = CombatRunner(
            self.ctx,
            battle_timeout=ABYSSAL_TIDE_BATTLE_TIMEOUT,
            dodge=False,
            afk_only=True,
        )
        return self._run_one_abyssal(runner)

    def _exit_abyssal_tide(self) -> None:
        from ..combat_prompts import dismiss_shackled_challenge_end, event_challenge_end
        from ..run_end_dismiss import needs_post_run_dismiss

        if is_lobby(self.ctx.device.screenshot()):
            return
        log.info("  Leaving Abyssal Tide -> campaign lobby")
        for _ in range(10):
            self.ctx.kill.check()
            img = self.ctx.device.screenshot()
            sid = self.ctx.current_screen()
            if is_lobby(img):
                log.info("  Campaign lobby reached")
                return
            if sid in DUNGEON_COMBAT:
                if needs_post_run_dismiss(img):
                    log.info("  Closing post-run Abyssal Tide")
                    dismiss_shackled_challenge_end(self.ctx)
                    sleep(0.8)
                elif self._resume_abyssal_combat():
                    continue
                else:
                    sleep(0.5)
                continue
            if event_challenge_end(img) or needs_post_run_dismiss(img):
                log.info("  Closing Challenge has ended screen")
                dismiss_shackled_challenge_end(self.ctx)
                sleep(0.8)
                continue
            if self._is_abyssal_tide_popup_screen(img):
                log.info("  Back from Abyssal Tide popup")
                self._opt("menu", "back", settle=0.8, money_check=False)
                sleep(0.8)
                continue
            if self._is_events_hub(img):
                log.info("  Events -> Campaign")
                self._go_campaign()
                sleep(1.0)
                continue
            if sid in (ScreenId.VICTORY, ScreenId.DEFEAT):
                self._opt("run_end", "continue", settle=0.5, money_check=False)
                sleep(0.6)
                continue
            self._opt("events", "dismiss_rewards", settle=0.5, money_check=False)
            self._opt("menu", "back", settle=0.5, money_check=False)
            self._go_campaign()
            sleep(0.8)
        if not is_lobby(self.ctx.device.screenshot()):
            log.warning("  Campaign lobby not confirmed after leaving Abyssal Tide")
            self.ensure_campaign_lobby()

    def _start_abyssal_tide_run(self, *, use_ad_ticket: bool = False) -> bool:
        if not self._is_abyssal_tide_popup():
            log.warning("    Start ignored: not on Abyssal Tide popup")
            return False
        if use_ad_ticket:
            log.info("    ad ticket -> select entry + double Start")
            self._select_abyssal_ad_entry()
            taps = 2
        else:
            log.info("    Start (ticket free)")
            taps = 1
        before = self.ctx.device.screenshot()
        self._abyssal_tide_tap_start(taps=taps)
        sleep(1.5)
        if self.ctx.current_screen() in DUNGEON_COMBAT:
            return True
        after = self.ctx.device.screenshot()
        if vision.difference(before, after) <= 0.015:
            if not use_ad_ticket and self._abyssal_ad_ticket_visible(after):
                log.info("    Start no response; retry with ad ticket + double Start")
                self._select_abyssal_ad_entry()
                self._abyssal_tide_tap_start(taps=2)
                sleep(1.5)
                return self.ctx.current_screen() in DUNGEON_COMBAT
            return False
        return self.ctx.current_screen() in DUNGEON_COMBAT

    def _abyssal_tide_tap_start(self, *, taps: int = 1) -> None:
        for i in range(taps):
            self._opt(
                "events",
                "abyssal_tide_start",
                settle=0.4 if i < taps - 1 else 1.0,
                money_check=False,
            )
            if i < taps - 1:
                sleep(0.7)

    def _select_abyssal_ad_entry(self) -> None:
        if not self._opt("events", "abyssal_tide_entry_ad", settle=0.6, money_check=False):
            self._opt("events", "shackled_jungle_entry_ad", settle=0.6, money_check=False)

    def _abyssal_ad_ticket_visible(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        if not self._is_abyssal_tide_popup_screen(img):
            return False
        try:
            p = self.ctx.coords.point("events", "abyssal_tide_entry_ad")
            x, y = p.x, p.y
        except ValueError:
            x, y = 320, 1100
        b, g, r = img[y, x]
        return int(g) > 90 or int(b) > 130 or (int(r) > 160 and int(g) > 100)

    def _abyssal_run_counted(self, result: str) -> bool:
        return result in ("victory", "defeat")

    def _run_one_abyssal(self, dungeon_combat: CombatRunner) -> bool:
        result = dungeon_combat.run_until_end()
        log.info("    result: %s", result)
        if not self._abyssal_run_counted(result):
            return False
        if not dungeon_combat.collect_event_end():
            log.warning("    Abyssal post-run not closed")
            return False
        sleep(0.8)
        return True

    def _events_abyssal_tide(self, *, resume: bool = False, from_popup: bool = False) -> int:
        max_runs = self.abyssal_tide_runs
        log.info("  Abyssal Tide (up to %d free + ad if visible, AFK)", max_runs)

        dungeon_combat = CombatRunner(
            self.ctx,
            battle_timeout=ABYSSAL_TIDE_BATTLE_TIMEOUT,
            dodge=False,
            afk_only=True,
        )

        completed = 0
        runs_left = max_runs
        self.ctx.hold_combat = True
        try:
            if resume or self._is_abyssal_combat_active():
                log.info("    resuming ongoing combat")
                if self._run_one_abyssal(dungeon_combat):
                    completed += 1
                runs_left -= 1
                if runs_left <= 0 and not self._abyssal_ad_ticket_visible():
                    return completed

            if not (from_popup or self._is_abyssal_tide_popup()):
                if not self._open_abyssal_tide_popup():
                    log.warning("  Could not open Abyssal Tide popup")
                    return completed

            for n in range(runs_left):
                run_num = max_runs - runs_left + n + 1
                log.info("    run %d/%d (free)", run_num, max_runs)
                if not self._start_abyssal_tide_run(use_ad_ticket=False):
                    log.info("    free Start unavailable; stopping free runs")
                    break
                if self._run_one_abyssal(dungeon_combat):
                    completed += 1
                if n + 1 >= runs_left:
                    break
                sleep(0.5)
                if not self._is_abyssal_tide_popup() and not self._open_abyssal_tide_popup():
                    break

            if self._is_abyssal_tide_popup() and self._abyssal_ad_ticket_visible():
                log.info("    run ad (ticket video visible)")
                if self._start_abyssal_tide_run(use_ad_ticket=True):
                    if self._run_one_abyssal(dungeon_combat):
                        completed += 1
        finally:
            self.ctx.hold_combat = False

        return completed

    def claim_arena(self) -> None:
        log.info("-> Events / Arena (%d fights)", self.arena_fights)
        if not self._arena_prepare_from_current_screen("arena_banner"):
            log.warning("  could not prepare Arena from current screen")
            return
        done = self._run_arena_fights("arena", fights=self.arena_fights)
        log.info("  Arena: %d/%d fights", done, self.arena_fights)
        self._leave_arena_to_campaign()
        if done > 0:
            self._finish_claim("arena")
        else:
            log.warning("Arena: 0 fights completed; not marking verified")

    def claim_peak_arena(self) -> None:
        log.info("-> Events / Peak Arena (%d fights)", self.arena_fights)
        if not self._arena_prepare_from_current_screen("peak_arena_banner"):
            log.warning("  could not prepare Peak Arena from current screen")
            return
        done = self._run_arena_fights("peak_arena", fights=self.arena_fights)
        log.info("  Peak Arena: %d/%d fights", done, self.arena_fights)
        self._leave_arena_to_campaign()
        if done > 0:
            self._finish_claim("peak_arena")
        else:
            log.warning("Peak Arena: 0 fights completed; not marking verified")

    def _challenge_runner(self):
        from .challenge_events import ChallengeEventRunner

        return ChallengeEventRunner(self.ctx)

    def _claim_challenge_event(self, claim_id: str) -> None:
        from .challenge_events import CHALLENGE_EVENTS

        spec = CHALLENGE_EVENTS.get(claim_id)
        if spec is None:
            log.error("Unknown challenge event: %s", claim_id)
            return
        runner = self._challenge_runner()
        try:
            completed = runner.run(spec)
            if completed > 0:
                self._finish_claim(claim_id)
            else:
                log.warning("%s: 0 verified runs; not marking verified", claim_id)
        finally:
            runner.exit_to_campaign(spec)
            self.ensure_campaign_lobby()

    def claim_rumble_ladder(self) -> None:
        log.info("-> Events / Challenge / Rumble Ladder")
        self._claim_challenge_event("rumble_ladder")

    def claim_seal_battle(self) -> None:
        log.info("-> Events / Challenge / Seal Battle (survival + circles)")
        self._claim_challenge_event("seal_battle")

    def claim_monster_invasion(self) -> None:
        log.info("-> Events / Challenge / Monster Invasion (survival + circles)")
        self._claim_challenge_event("monster_invasion")

    def claim_magic_plant_defense(self) -> None:
        log.info("-> Events / Challenge / Magic Plant Defense (survival + circles)")
        self._claim_challenge_event("magic_plant_defense")

    def _is_arena_personal_info_overlay(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        return vision.is_arena_personal_info_overlay(img)

    def _arena_read_state(self, screen=None) -> ArenaScreenState:
        img = screen if screen is not None else self.ctx.device.screenshot()
        sid = identify(img)
        arena = identify_arena(img)
        rivals: dict[int, float | None] = {}
        if vision.is_arena_opponents_popup(img):
            for index in range(ARENA_OPPONENT_INDEX, 6):
                row_i = max(0, index - 1)
                rivals[index] = vision.read_arena_opponent_power(img, row_i)
        return ArenaScreenState(
            screen=sid,
            arena=arena,
            on_lobby=is_lobby(img),
            rivals=rivals,
        )

    def _log_arena_state(self, label: str) -> ArenaScreenState:
        st = self._arena_read_state()
        if st.rivals:
            parts = []
            for index in range(ARENA_OPPONENT_INDEX, 6):
                power = st.rivals.get(index)
                parts.append(f"#{index}={power:.2f}M" if power is not None else f"#{index}=?")
            rival_txt = " ".join(parts)
        else:
            rival_txt = "no rivals popup"
        log.info(
            "  [%s] screen=%s arena=%s lobby=%s | %s",
            label,
            st.screen.value,
            st.arena.value if st.arena else "-",
            st.on_lobby,
            rival_txt,
        )
        return st

    def _arena_prepare_from_current_screen(self, banner_key: str = "arena_banner") -> bool:
        self._log_arena_state("start")
        for step in range(8):
            st = self._arena_read_state()
            if st.arena == ScreenId.ARENA_OPPONENTS and st.rivals_readable:
                self._log_arena_state("ready")
                return True
            if st.arena == ScreenId.ARENA_OPPONENTS:
                log.info("  [prepare/%d] rivals popup, waiting for OCR...", step + 1)
                if self._wait_arena_rivals_readable(timeout=12.0):
                    self._log_arena_state("ready")
                    return True
                continue
            if st.arena == ScreenId.ARENA_PERSONAL_INFO:
                log.info("  [prepare/%d] Personal Info -> back", step + 1)
                self._dismiss_arena_personal_info()
                sleep(0.4)
                continue
            if st.arena == ScreenId.ARENA_LEADERBOARD:
                log.info("  [prepare/%d] leaderboard -> Challenge", step + 1)
                if not self._opt("events", "arena_challenge", settle=0.5, money_check=False):
                    return False
                sleep(0.5)
                continue
            if st.screen == ScreenId.BATTLE:
                log.info("  [prepare/%d] combat -> Exit Battle", step + 1)
                self._exit_battle()
                sleep(self.arena_reload_after_exit_s)
                continue
            if self._is_arena_victory_screen():
                log.info("  [prepare/%d] victory -> Confirm", step + 1)
                self._tap_arena_confirm()
                sleep(0.5)
                continue
            if st.on_lobby or st.screen == ScreenId.LOBBY:
                log.info("  [prepare/%d] lobby -> navigate to Arena", step + 1)
                if self._open_arena_rivals_popup(banner_key) and self._arena_rivals_readable():
                    self._log_arena_state("ready")
                    return True
                continue
            if self._is_events_hub():
                log.info("  [prepare/%d] events hub -> open rivals", step + 1)
                if self._open_arena_rivals_popup(banner_key) and self._arena_rivals_readable():
                    self._log_arena_state("ready")
                    return True
                continue
            if self._arena_recover_screen(banner_key):
                self._log_arena_state("ready")
                return True
            log.info(
                "  [prepare/%d] screen=%s no direct route -> open Arena",
                step + 1,
                st.screen.value,
            )
            if self._open_arena_rivals_popup(banner_key) and self._arena_rivals_readable():
                self._log_arena_state("ready")
                return True
        ok = self._is_arena_opponents_popup() and self._arena_rivals_readable()
        if not ok:
            self._log_arena_state("prepare failed")
        return ok

    def _dismiss_arena_personal_info(self) -> bool:
        if not self._is_arena_personal_info_overlay():
            return False
        if self._is_arena_opponents_popup() and self._arena_rivals_readable():
            return False
        log.info("  closing Personal Info (back, not Challenge popup X)")
        self._back()
        sleep(0.5)
        return True

    def _is_arena_opponents_popup(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        return vision.is_arena_opponents_popup(img)

    def _is_arena_leaderboard(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        return vision.is_arena_leaderboard(img)

    def _arena_recover_screen(self, banner_key: str = "arena_banner") -> bool:
        for attempt in range(6):
            self.ctx.kill.check()
            screen = self.ctx.device.screenshot()
            if is_lobby(screen):
                return False

            if self._is_arena_opponents_popup(screen):
                if self._arena_rivals_readable():
                    return True
                wait_s = 8.0 if self.arena_exit_early else 12.0
                if self._wait_arena_rivals_readable(timeout=wait_s):
                    return True

            sid = identify_arena(screen)

            if sid == ScreenId.ARENA_PERSONAL_INFO:
                self._dismiss_arena_personal_info()
                sleep(0.35 if self.arena_exit_early else 0.6)
                continue

            if sid == ScreenId.ARENA_OPPONENTS:
                if self._arena_rivals_readable():
                    return True
                wait_s = 8.0 if self.arena_exit_early else 12.0
                if self._wait_arena_rivals_readable(timeout=wait_s):
                    return True
                continue

            if self.ctx.current_screen() == ScreenId.BATTLE:
                log.info("  Arena: active combat -> Exit Battle")
                self._exit_battle()
                sleep(self.arena_reload_after_exit_s)
                continue

            if sid == ScreenId.ARENA_LEADERBOARD or self._is_arena_leaderboard(screen):
                log.info("  Arena: leaderboard -> Challenge")
                if not self._opt("events", "arena_challenge", settle=0.5, money_check=False):
                    return False
                if self._wait_arena_rivals_readable(timeout=15.0 if self.arena_exit_early else 20.0):
                    return True
                continue

            if self._is_arena_victory_screen(screen):
                log.info("  Arena: pending victory -> Confirm")
                self._tap_arena_confirm()
                sleep(0.5 if self.arena_exit_early else 1.0)
                continue

            return False
        return self._is_arena_opponents_popup() and self._arena_rivals_readable()

    def _open_arena_rivals_popup(self, banner_key: str) -> bool:
        if self._arena_recover_screen(banner_key):
            return True
        if self._is_arena_opponents_popup():
            return True
        if self._is_arena_leaderboard():
            log.info("  Arena: already on leaderboard -> Challenge")
            if not self._opt("events", "arena_challenge", settle=0.8, money_check=False):
                return False
            return self._wait_arena_opponents(timeout=12.0)
        if not self._ensure_events_hub():
            return False
        self._opt("events", "tab_arena", settle=1.0, money_check=False)
        if not self._opt("events", banner_key, settle=1.5, money_check=False):
            return False
        sleep(0.8)
        if self._is_arena_opponents_popup():
            return True
        if not self._opt("events", "arena_challenge", settle=0.8, money_check=False):
            return False
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            if self._is_arena_opponents_popup():
                return True
            sleep(0.45)
        log.warning("  Arena rivals popup not detected")
        return False

    def _read_arena_opponent_power(self, index: int = ARENA_OPPONENT_INDEX) -> float | None:
        row_i = max(0, index - 1)
        return vision.read_arena_opponent_power(self.ctx.device.screenshot(), row_i)

    def _arena_row_tap_y(self, index: int = ARENA_OPPONENT_INDEX) -> int:
        screen = self.ctx.device.screenshot()
        rows = vision.find_arena_power_row_ys(screen)
        row_i = max(0, index - 1)
        if len(rows) > row_i:
            return rows[row_i]
        title_y = vision.arena_popup_title_y(screen)
        if title_y is not None and row_i < len(vision.ARENA_ROW_OFFSETS):
            return title_y + vision.ARENA_ROW_OFFSETS[row_i]
        return ARENA_RIVAL_ROW_Y_FALLBACK.get(index, ARENA_RIVAL_ROW_Y_FALLBACK[3])

    def _arena_attack_opponent(self, index: int = ARENA_OPPONENT_INDEX) -> None:
        row_y = self._arena_row_tap_y(index)
        screen = self.ctx.device.screenshot()
        tap = vision.find_arena_rival_challenge_tap(screen, row_y)
        if tap is not None:
            x, y = tap
        else:
            x, y = ARENA_RIVAL_CHALLENGE_X, row_y
        log.info(
            "  Challenge rival #%d @ (%d,%d) (yellow button, not avatar)",
            index,
            x,
            y,
        )
        settle = 0.8 if self.arena_exit_early else 1.0
        self._tap(x, y, settle=settle)
        self.ctx.device.swipe(x, y, x, y, 120)
        sleep(0.25)

    def _arena_refresh_opponents(self) -> bool:
        before = self._arena_read_rivals()
        try:
            match = vision.find_template(
                self.ctx.device.screenshot(),
                "anchors/arena_free_refresh.png",
                region=(200, 1210, 500, 90),
            )
            if match.confidence >= 0.62:
                log.info("  refresh (template conf=%.2f)", match.confidence)
                self.ctx.tap(match.cx, match.cy, money_check=False, settle=0.0)
            else:
                self._opt("events", "arena_refresh", settle=0.0, money_check=False)
        except FileNotFoundError:
            self._opt("events", "arena_refresh", settle=0.0, money_check=False)
        sleep(ARENA_REFRESH_SETTLE_S)
        self._wait_arena_opponents(timeout=8.0)
        after = self._arena_read_rivals()
        if before == after:
            log.warning("  refresh with no change in rivals")
            return False
        return True

    def _is_arena_victory_screen(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        if self._is_arena_opponents_popup(img):
            return False
        if self._is_arena_leaderboard(img):
            return False
        if self._is_arena_personal_info_overlay(img):
            return False
        try:
            return vision.matches(
                img,
                "anchors/arena_victory.png",
                threshold=0.68,
                region=(280, 350, 340, 200),
            )
        except FileNotFoundError:
            pass
        return False

    def _arena_rivals_readable(self) -> bool:
        return any(p is not None for p in self._arena_read_rivals().values())

    def _wait_arena_rivals_readable(self, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            if self._is_arena_opponents_popup() and self._arena_rivals_readable():
                return True
            sleep(0.45)
        return False

    def _ensure_arena_challenge_popup(self, banner_key: str = "arena_banner") -> bool:
        st = self._log_arena_state("pre-fight")
        if st.arena == ScreenId.ARENA_OPPONENTS and st.rivals_readable:
            return True
        if self._is_arena_opponents_popup():
            if self._arena_rivals_readable():
                return True
            if self._wait_arena_rivals_readable(timeout=10.0):
                return True
        if self._arena_recover_screen(banner_key):
            return True
        if self._is_arena_leaderboard():
            log.info("  Arena: on leaderboard -> Challenge")
            if not self._opt("events", "arena_challenge", settle=0.5, money_check=False):
                return False
            return self._wait_arena_rivals_readable(timeout=12.0)
        return self._open_arena_rivals_popup(banner_key) and self._arena_rivals_readable()

    def _tap_arena_confirm(self) -> None:
        self._opt("events", "arena_confirm", settle=1.5, money_check=False)

    def _wait_arena_victory_and_confirm(self) -> bool:
        deadline = time.monotonic() + ARENA_VICTORY_TIMEOUT
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            screen = self.ctx.device.screenshot()
            if self._is_arena_victory_screen(screen):
                log.info("  arena victory -> Confirm")
                self._tap_arena_confirm()
                sleep(1.0)
                return True
            arena_sid = identify_arena(screen)
            if arena_sid == ScreenId.ARENA_PERSONAL_INFO:
                self._dismiss_arena_personal_info()
                sleep(0.6)
                continue
            if arena_sid == ScreenId.ARENA_OPPONENTS:
                log.info("  rivals popup (arena end)")
                return True
            if arena_sid == ScreenId.ARENA_LEADERBOARD:
                log.info("  arena leaderboard (combat end)")
                return True
            if self.ctx.current_screen() == ScreenId.BATTLE:
                log.info("  still in combat; waiting for arena end...")
            else:
                sid = self.ctx.current_screen()
                log.info("  waiting for arena end (%s)...", sid.value)
            sleep(ARENA_VICTORY_POLL_S)
        log.warning("  arena end timeout (%.0fs); attempting to exit combat", ARENA_VICTORY_TIMEOUT)
        if self.ctx.current_screen() == ScreenId.BATTLE:
            self._exit_battle()
        return self._is_arena_opponents_popup() or self._is_arena_victory_screen()

    def _is_arena_combat_active(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        if self._is_arena_victory_screen(img):
            return True
        sid = identify_combat(img)
        return sid in (
            ScreenId.BATTLE,
            ScreenId.SKILL_SELECT,
            ScreenId.ROULETTE,
            ScreenId.VICTORY,
            ScreenId.DEFEAT,
        )

    def _wait_for_battle_start(self, timeout: float = 18.0, *, target: int | None = None) -> bool:
        deadline = time.monotonic() + timeout
        retried = False
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            screen = self.ctx.device.screenshot()
            if self._is_arena_combat_active(screen):
                if self._is_arena_victory_screen(screen):
                    log.info("  fight ended (arena victory)")
                else:
                    log.info("  combat detected (%s)", identify_combat(screen).value)
                return True
            if self._is_arena_personal_info_overlay(screen):
                log.warning("  Personal Info opened instead of combat")
                return False
            if not self._is_arena_opponents_popup(screen) and not self._is_arena_leaderboard(screen):
                sleep(0.35)
                continue
            if (
                target is not None
                and not retried
                and time.monotonic() > deadline - timeout + 5.0
            ):
                log.info("  still on rivals popup; retry Challenge tap #%d", target)
                self._arena_attack_opponent(target)
                retried = True
            sleep(0.35)
        return False

    def _arena_return_to_rivals(self, banner_key: str) -> bool:
        reload_s = self.arena_reload_after_exit_s if self.arena_exit_early else 1.5
        log.info("  waiting for rivals popup (up to %.0fs)", reload_s + 20.0)
        sleep(reload_s)
        self._log_arena_state("post-exit")
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            if self._is_arena_opponents_popup() and self._arena_rivals_readable():
                return True
            if self._is_arena_personal_info_overlay():
                log.info("  post-fight: Personal Info -> back")
                self._back()
                sleep(0.4)
                continue
            if self._is_arena_leaderboard():
                log.info("  post-fight: leaderboard -> Challenge")
                if not self._opt("events", "arena_challenge", settle=0.5, money_check=False):
                    return False
                sleep(0.6)
                continue
            if self._is_arena_victory_screen():
                self._tap_arena_confirm()
                sleep(0.8)
                continue
            if self._is_arena_combat_active(screen) or self.ctx.current_screen() == ScreenId.BATTLE:
                self._exit_battle()
                sleep(reload_s)
                continue
            sleep(0.45)
        if self._arena_recover_screen(banner_key):
            return True
        log.warning("  readable rivals popup did not return")
        return False

    def _wait_arena_opponents(self, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            if self._is_arena_opponents_popup():
                return True
            sleep(0.35)
        return False

    def _arena_read_rivals(self) -> dict[int, float | None]:
        screen = self.ctx.device.screenshot()
        rivals: dict[int, float | None] = {}
        for index in range(ARENA_OPPONENT_INDEX, 6):
            row_i = max(0, index - 1)
            rivals[index] = vision.read_arena_opponent_power(screen, row_i)
        return rivals

    def _arena_log_rivals(self, rivals: dict[int, float | None] | None = None) -> dict[int, float | None]:
        if rivals is None:
            rivals = self._arena_read_rivals()
        for index in range(ARENA_OPPONENT_INDEX, 6):
            power = rivals.get(index)
            if power is None:
                log.info("  rival #%d power=?", index)
            else:
                log.info("  rival #%d power=%.2fM", index, power)
        return rivals

    def _arena_first_under_max(
        self,
        max_power: float,
        rivals: dict[int, float | None],
    ) -> int | None:
        for index in range(ARENA_OPPONENT_INDEX, 6):
            power = rivals.get(index)
            if power is None:
                continue
            if power < max_power:
                return index
        return None

    def _arena_confirm_before_attack(self, rivals: dict[int, float | None], target: int) -> bool:
        if not self.arena_confirm:
            return True

        max_power = self.arena_max_power
        log.info("=== OCR readings (confirm before attack) ===")
        for index in range(ARENA_OPPONENT_INDEX, 6):
            power = rivals.get(index)
            if power is None:
                label = "?"
            else:
                label = f"{power:.2f}M"
            extra = ""
            if index == target:
                extra = "  <- ATTACK"
            elif power is not None and power >= max_power:
                extra = "  (above cap)"
            log.info("  rival #%d: %s%s", index, label, extra)

        screen = self.ctx.device.screenshot()
        shot_path = ROOT / "screenshots" / "arena-pre-attack.png"
        cv2.imwrite(str(shot_path), screen)
        log.info("Rivals screenshot: screenshots/arena-pre-attack.png")

        wait_s = self.arena_confirm_wait
        if wait_s is None:
            wait_s = 15.0

        if wait_s > 0:
            log.info("Waiting %.0fs before attacking rival #%d...", wait_s, target)
            sleep(wait_s)
            return True

        if sys.stdin.isatty():
            try:
                ans = input(f"Attack rival #{target}? [Enter=yes / n=cancel]: ").strip().lower()
            except EOFError:
                return True
            if ans == "n":
                log.info("Attack cancelled by user")
                return False
            return True

        log.warning("No interactive stdin; continuing without extra pause")
        return True

    def _arena_pick_target(self) -> int | None:
        max_power = self.arena_max_power
        rivals = self._arena_log_rivals()
        target = self._arena_first_under_max(max_power, rivals)
        if target is not None:
            power = rivals.get(target)
            log.info(
                "  pick rival #%d (topmost under %.2fM, read %.2fM)",
                target,
                max_power,
                power or 0.0,
            )
            return target

        for refresh_i in range(ARENA_REFRESH_BEFORE_FALLBACK):
            log.info(
                "  no rival under %.2fM; refresh %d/%d",
                max_power,
                refresh_i + 1,
                ARENA_REFRESH_BEFORE_FALLBACK,
            )
            before = rivals
            if not self._arena_refresh_opponents():
                log.warning("  ineffective refresh; stopping retries")
                break
            rivals = self._arena_log_rivals()
            target = self._arena_first_under_max(max_power, rivals)
            if target is not None:
                power = rivals.get(target)
                log.info(
                    "  pick rival #%d (topmost under %.2fM, read %.2fM)",
                    target,
                    max_power,
                    power or 0.0,
                )
                return target

        log.warning(
            "  no rival under %.2fM after %d refreshes; fallback to weakest",
            max_power,
            ARENA_REFRESH_BEFORE_FALLBACK,
        )
        weakest_index: int | None = None
        weakest_power: float | None = None
        for index in range(ARENA_OPPONENT_INDEX, 6):
            power = rivals.get(index)
            if power is None:
                continue
            if weakest_power is None or power < weakest_power:
                weakest_power = power
                weakest_index = index
        if weakest_index is not None and weakest_power is not None:
            log.info(
                "  pick rival #%d (weakest fallback, read %.2fM)",
                weakest_index,
                weakest_power,
            )
            return weakest_index
        return None

    def _arena_abort_battle_and_return(self, banner_key: str) -> bool:
        log.info(
            "  arena exit early: active combat, waiting %.0fs before exit",
            self.arena_battle_abort_s,
        )
        sleep(self.arena_battle_abort_s)
        if self._is_arena_combat_active() or self.ctx.current_screen() == ScreenId.BATTLE:
            log.info("  arena exit early: pause -> Exit Battle -> Confirm")
            self._exit_battle()
        elif self._is_arena_victory_screen():
            log.info("  arena exit early: quick victory -> Confirm")
            self._tap_arena_confirm()
        else:
            log.warning(
                "  arena exit early: unexpected screen (%s)",
                self.ctx.current_screen().value,
            )
        return self._arena_return_to_rivals(banner_key)

    def _arena_pick_opponent_once(
        self,
        banner_key: str = "arena_banner",
        *,
        return_to_rivals: bool = True,
    ) -> bool:
        target = self._arena_pick_target()
        if target is None:
            return False

        rivals = self._arena_read_rivals()
        if not self._arena_confirm_before_attack(rivals, target):
            return False

        log.info("  attack rival #%d", target)
        self._arena_attack_opponent(target)
        sleep(0.8 if self.arena_exit_early else 1.0)

        if not self._wait_for_battle_start(timeout=45.0, target=target):
            log.warning("  combat did not start after rival Challenge tap")
            self._dismiss_arena_personal_info()
            return False

        if self._is_arena_victory_screen():
            log.info("  arena victory -> Confirm")
            self._tap_arena_confirm()
            if not return_to_rivals:
                return True
            return self._arena_return_to_rivals(banner_key)

        log.info("  combat started")

        if self.arena_exit_early:
            return self._arena_abort_battle_and_return(banner_key)

        if not self._wait_arena_victory_and_confirm():
            log.warning("  arena victory did not close")
            if self._is_arena_victory_screen():
                self._tap_arena_confirm()

        if not return_to_rivals:
            return True

        return self._arena_return_to_rivals(banner_key)

    def _run_arena_fights(self, mode: str, *, fights: int) -> int:
        banner = "arena_banner" if mode == "arena" else "peak_arena_banner"
        log.info("  %s (%d fights)", mode, fights)

        gap = 0.15 if self.arena_exit_early else 0.8
        completed = 0
        for n in range(fights):
            log.info("    fight %d/%d", n + 1, fights)
            if not self._ensure_arena_challenge_popup(banner):
                log.warning("  could not open readable Challenge popup")
                break
            is_last = n + 1 >= fights
            if self._arena_pick_opponent_once(banner, return_to_rivals=not is_last):
                completed += 1
            else:
                break
            if not is_last:
                sleep(gap)
        return completed

    def _leave_arena_to_campaign(self) -> None:
        log.info("  leaving Arena -> campaign lobby")
        self._dismiss_arena_personal_info()
        if self._is_arena_victory_screen():
            self._tap_arena_confirm()
            sleep(0.5)
        if self._is_arena_opponents_popup():
            log.info("  closing Challenge popup")
            self._back()
            sleep(0.4)
        elif identify_arena(self.ctx.device.screenshot()) is not None:
            self._back()
            sleep(0.35)
        for _ in range(3):
            if is_lobby(self.ctx.device.screenshot()):
                log.info("  campaign lobby reached")
                return
            self._back()
            sleep(0.35)
        self._go_campaign()
        if is_lobby(self.ctx.device.screenshot()):
            log.info("  campaign lobby reached")
            return
        log.warning("  campaign lobby not confirmed after leaving Arena (not restarting emulator)")

    def _events_arena_mode(self, mode: str, *, fights: int) -> None:
        self._run_arena_fights(mode, fights=fights)

    def _pick_arena_opponent(self) -> None:
        self._arena_pick_opponent_once()

    def claim_great_value(self) -> None:
        log.info("-> Great Value")
        if not self._lobby_badge("lobby", "great_value"):
            log.info("No badge on Great Value; skipping")
            return
        if not self._opt("lobby", "great_value", settle=1.2, money_check=False):
            return
        claimed = False
        for key in ("free_bonus", "free_bonus_alt_1", "free_bonus_alt_2"):
            claimed |= self._tap_optional_reward("great_value", key, settle=0.8, money_check=False, dismiss_times=2)
            if claimed:
                break
        self._back()
        self._go_campaign()
        if claimed:
            self._finish_claim("great_value")
        else:
            log.warning("Great Value opened but could not confirm free; not marking verified")

    def claim_privilege(self) -> None:
        log.info("-> Privilege Card")
        if not self._lobby_badge("lobby", "privilege_card"):
            log.info("No badge on Privilege; skipping")
            return
        if not self._opt("lobby", "privilege_card", settle=1.2, money_check=False):
            return
        self._claim_all_generic("privilege")
        self._back()
        self._back()
        self._go_campaign()
        self._finish_claim("privilege")

    def claim_messages(self) -> None:
        log.info("-> Messages")
        has_mail = self._lobby_badge("lobby", "messages")
        if not has_mail:
            log.info("No badge on Messages; skipping")
            return
        if not self._opt("lobby", "messages", settle=1.2, money_check=False):
            return
        self._claim_all_generic("messages")
        self._back()
        self._finish_claim("messages")

    def claim_guild(self) -> None:
        log.info("-> Guild (merchant, hall, expedition)")
        if not self._opt("lobby", "guild", settle=2.5):
            return
        sleep(1.5)
        self._guild_merchant()
        self._guild_hall_legacy()
        self._guild_expedition()
        self._back()
        self._finish_claim("guild")

    def _guild_dismiss_rewards(self) -> None:
        self._opt("guild", "dismiss_empty", settle=0.5, money_check=False)

    def _guild_badge(self, key: str) -> bool:
        try:
            p = self.ctx.coords.point("guild", key)
        except (KeyError, ValueError):
            return False
        return has_red_badge(self.ctx.device.screenshot(), p.x, p.y)

    def _guild_merchant(self) -> None:
        log.info("  Guild Merchant")
        if not self._opt("guild", "merchant", settle=1.2):
            return
        if self._guild_badge("bargain"):
            before = self.ctx.device.screenshot()
            self._opt("guild", "bargain", settle=1.0, money_check=False)
            sleep(1.5)
            if vision.difference(before, self.ctx.device.screenshot()) > 0.015:
                log.info("    Bargain rewards -> tap empty")
                self._guild_dismiss_rewards()
            else:
                log.info("    Bargain with no popup (already done or loading)")
        else:
            log.info("    No badge on Bargain; skipping (Purchase costs gems)")
        self._back()

    def _guild_dismiss_legacy_reward(self) -> None:
        try:
            self._opt("guild", "legacy_dismiss", settle=0.4, money_check=False)
        except ValueError:
            self._guild_dismiss_rewards()

    def _try_emulator_recovery(self, reason: str) -> bool:
        if not self.recover_emulator or self._emulator_recovery_used:
            return False
        self._emulator_recovery_used = True
        log.warning(
            "%s — restarting emulator (only automatic recovery per session)...",
            reason,
        )
        from ..recovery import reboot_emulator_and_wait_lobby

        return reboot_emulator_and_wait_lobby(self.ctx.device)

    _try_ldplayer_recovery = _try_emulator_recovery

    def _guild_wait_legacy_idle(self, timeout: float = 25.0) -> bool:
        """Espera a que desaparezca el loading del popup Legacy."""
        deadline = time.time() + timeout
        stable_reads = 0
        prev_roi = None
        while time.time() < deadline:
            screen = self.ctx.device.screenshot()
            roi = vision.crop(screen, LEGACY_LOADING_REGION)
            if prev_roi is not None and vision.difference(prev_roi, roi) < 0.008:
                stable_reads += 1
                if stable_reads >= 4:
                    return True
            else:
                stable_reads = 0
            prev_roi = roi
            sleep(0.35)
        log.warning("Legacy loading stuck (>%.0fs)", timeout)
        return False

    def _guild_legacy_donate_once(self) -> bool:
        if not self._guild_wait_legacy_idle():
            return False
        before = self.ctx.device.screenshot()
        self._opt("guild", "legacy_donate", settle=0.3, money_check=False)
        deadline = time.time() + 20.0
        while time.time() < deadline:
            sleep(0.45)
            after = self.ctx.device.screenshot()
            if vision.difference(before, after) > 0.018:
                sleep(1.2)
                self._guild_dismiss_legacy_reward()
                self._guild_wait_legacy_idle(timeout=15.0)
                return True
        log.warning("Legacy donate no on-screen response")
        return False

    def _guild_hall_legacy(self, *, _after_recovery: bool = False) -> None:
        log.info("  Guild Hall -> Research -> Legacy (5 donations: Free, 20, 40, 60, 80)")
        if not self._opt("guild", "hall", settle=1.5):
            return
        if not self._opt("guild", "research", settle=1.2):
            self._back()
            return
        if not self._opt("guild", "legacy", settle=1.0):
            self._back()
            self._back()
            return
        sleep(1.5)
        if not self._guild_wait_legacy_idle():
            if not _after_recovery and self._try_ldplayer_recovery("Legacy loading on open"):
                log.info("  Retrying Legacy after LDPlayer reboot...")
                if self._opt("lobby", "guild", settle=2.5):
                    sleep(1.5)
                    return self._guild_hall_legacy(_after_recovery=True)
            log.info("    Legacy blocked; skipping donations")
            self._opt("menu", "close_x", settle=0.6, money_check=False)
            self._back()
            self._back()
            return

        done = 0
        for n in range(GUILD_LEGACY_DONATIONS):
            log.info("    Legacy donate %d/%d", n + 1, GUILD_LEGACY_DONATIONS)
            if not self._guild_legacy_donate_once():
                if not _after_recovery and self._try_ldplayer_recovery("Legacy donate no response"):
                    log.info("  Retrying Legacy after LDPlayer reboot...")
                    if self._opt("lobby", "guild", settle=2.5):
                        sleep(1.5)
                        return self._guild_hall_legacy(_after_recovery=True)
                log.info("    No donations left or loading blocked")
                break
            done += 1

        log.info("    Legacy donations completed: %d/%d", done, GUILD_LEGACY_DONATIONS)
        self._opt("menu", "close_x", settle=0.6, money_check=False)
        self._back()
        self._back()

    def _guild_expedition(self) -> None:
        log.info("  Guild Expedition")
        if not self._opt("guild", "expedition", settle=1.5):
            return
        if self._guild_badge("expedition_schedule"):
            before = self.ctx.device.screenshot()
            self._opt("guild", "expedition_schedule", settle=1.0, money_check=False)
            sleep(1.5)
            if vision.difference(before, self.ctx.device.screenshot()) > 0.015:
                log.info("    Schedule rewards -> tap empty")
                self._guild_dismiss_rewards()
            self._opt("menu", "close_x", settle=0.5, money_check=False)
        else:
            log.info("    No badge on Schedule; skipping")
        self._back()

    def _hunt_dismiss_rewards(self, *, wait_s: float = 2.0) -> None:
        sleep(wait_s)
        self._opt("hunt", "close_popup", settle=0.6, money_check=False)

    def claim_hunt(self) -> None:
        log.info("-> Hunt (Claim + Quick Hunt free + x5)")
        if not self._opt("lobby", "hunt", settle=1.2, money_check=False):
            return
        touched = False
        if self._opt("hunt", "claim", settle=0.8, money_check=False):
            log.info("  Hunt claim: waiting for rewards and closing bottom overlay")
            self._hunt_dismiss_rewards(wait_s=2.0)
            touched = True
        if self._opt("hunt", "quick_hunt", settle=1.2, money_check=False):
            free_chances = self._hunt_quick_chances("quick_free")
            if free_chances is None:
                free_chances = 2 if self._hunt_quick_available("quick_free") else 0
            log.info("  Quick Hunt free chances: %s", free_chances)
            for _ in range(min(2, max(0, free_chances))):
                if free_chances is None and not self._hunt_quick_available("quick_free"):
                    log.info("  Quick Hunt: no daily free/ticket visible on quick_free; skipping")
                    break
                if not self._tap_optional_reward(
                    "hunt",
                    "quick_free",
                    settle=0.6,
                    money_check=False,
                    dismiss_times=0,
                    dismiss_cb=lambda: self._hunt_dismiss_rewards(wait_s=1.0),
                ):
                    break
                touched = True

            x5_chances = self._hunt_quick_chances("quick_x5")
            log.info("  Quick Hunt x5 chances: %s", x5_chances if x5_chances is not None else "(unreadable)")
            for _ in range(min(3, max(0, x5_chances or 0))):
                if not self._tap_optional_reward(
                    "hunt",
                    "quick_x5",
                    settle=0.6,
                    money_check=False,
                    dismiss_times=0,
                    dismiss_cb=lambda: self._hunt_dismiss_rewards(wait_s=1.0),
                ):
                    break
                touched = True
            self._opt("hunt", "close_quick_popup", settle=0.4, money_check=False)
        self._opt("hunt", "close_popup", settle=0.4, money_check=False)
        if touched or not self._lobby_badge("lobby", "hunt"):
            self._finish_claim("hunt")
        else:
            log.warning("Hunt opened but did not confirm rewards; not marking verified")

    def claim_sidebar_events(self) -> None:
        log.info("-> Sidebar events (island, angler, campaign rout)")
        for claim_id, lobby_key, handler in (
            ("island_treasure", "island_treasure", self.claim_island_treasure),
            ("angler_bounty", "angler_bounty", self.claim_angler_bounty),
            ("campaign_rout", "campaign_rout", self.claim_campaign_rout),
        ):
            if not self.checks.should_run(claim_id):
                continue
            self.ensure_campaign_lobby()
            if not self._lobby_badge("lobby", lobby_key):
                log.info("No badge on %s; skipping", claim_id)
                continue
            if handler() is False:
                log.warning("%s did not complete minimum steps; not marking verified", claim_id)
            else:
                self._finish_claim(claim_id)
        self._finish_claim("sidebar_events")

    # --- Claims opcionales (fuera del loop principal) ---

    def claim_task_center(self) -> None:
        log.info("-> Task Center")
        if not self._opt("lobby", "task_center", settle=1.5):
            return
        if self._opt("task_center", "tab_sign_in", settle=0.8, money_check=False):
            self._claim_task_rows(SIGN_IN_CLAIM_ROWS)
        if self._opt("task_center", "tab_daily", settle=0.8, money_check=False):
            self._claim_task_rows(DAILY_CLAIM_ROWS)
            for key in MILESTONE_KEYS:
                self._opt("task_center", key, settle=0.5, money_check=False)
        if self._opt("task_center", "tab_weekly", settle=0.8, money_check=False):
            self._claim_task_rows(WEEKLY_CLAIM_ROWS)
        if self._opt("task_center", "tab_achievements", settle=0.8, money_check=False):
            self._claim_task_rows(ACHIEVEMENT_CLAIM_ROWS)
        self._opt("menu", "close_x", settle=0.6, money_check=False)

    def claim_friends(self) -> None:
        log.info("-> Friends (Claim & Gift All) — outside main loop")
        if not self._opt("lobby", "friends", settle=1.5):
            return
        self._opt("friends", "claim_gift_all", settle=1.0, money_check=False)
        self._dismiss_reward_popup(1)
        self._opt("menu", "close_x", settle=0.6, money_check=False)

    def claim_island_treasure(self) -> bool:
        log.info("-> Island Treasure")
        if not self._opt("lobby", "island_treasure", settle=1.2):
            return False
        opened = True
        if self._opt("island_treasure", "pack_tab", settle=1.0):
            self._tap_optional_reward("island_treasure", "pack1_free", settle=0.8, money_check=True)
            self._tap_optional_reward("island_treasure", "pack2_free", settle=0.8, money_check=True)
            opened = True
        self._back()
        self._back()
        self._go_campaign()
        return opened

    def claim_angler_bounty(self) -> None:
        log.info("-> Angler's Bounty")
        if not self._opt("lobby", "angler_bounty", settle=1.5):
            return
        if self._opt("angler_bounty", "pack", settle=1.0, money_check=False):
            self._opt("angler_bounty", "pack1_free", settle=0.6, money_check=False)
            self._dismiss_reward_popup(1)
            self._opt("angler_bounty", "pack2_free", settle=0.6, money_check=False)
            self._dismiss_reward_popup(1)
            self._opt("hunt", "close_popup", settle=0.4, money_check=False)
        if self._opt("angler_bounty", "tasks", settle=1.0, money_check=False):
            self._tap_claim_column(750, (420, 580, 740, 900, 1060))
            self._dismiss_reward_popup(1)
            self._opt("angler_bounty", "close", settle=0.4, money_check=False)
        self._opt("angler_bounty", "back", settle=0.6, money_check=False)

    def claim_campaign_rout(self) -> None:
        log.info("-> Campaign Rout")
        if not self._opt("lobby", "campaign_rout", settle=1.5):
            return
        if self._opt("campaign_rout", "tasks", settle=1.0):
            self._opt("campaign_rout", "tasks_claim", settle=0.8)
            self._opt("menu", "close_x", settle=0.6, money_check=False)
        if self._opt("campaign_rout", "pack", settle=1.0):
            self._opt("campaign_rout", "pack1_free", settle=0.8)
            self._dismiss_reward_popup(1)
            self._opt("campaign_rout", "pack2_free", settle=0.8)
            self._dismiss_reward_popup(2)
        if self._opt("campaign_rout", "fund", settle=1.0):
            self._opt("campaign_rout", "fund_claim_all", settle=0.8, money_check=False)
            self._dismiss_reward_popup(1)
        self._back()

    def claim_camp(self) -> None:
        log.info("-> Camp (gift bubbles AFK)")
        if not self._opt("lobby", "camp", settle=1.2, money_check=False):
            return
        for key in ("gift_center", "gift_left", "gift_edge"):
            if self._opt("camp", key, settle=0.5, money_check=False):
                self._dismiss_reward_popup(2)
        self._opt("camp", "back", settle=0.6, money_check=False)

    def _rune_ruins_brown_background(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        try:
            p = self.ctx.coords.point("rune_ruins", "chest_right")
            b, g, r = img[p.y, p.x]
        except ValueError:
            b, g, r = img[760, 620]
        return int(r) > 120 and int(g) > 90 and int(b) < 140

    def _rune_ruins_key_reward_count(self, screen=None) -> int | None:
        img = screen if screen is not None else self.ctx.device.screenshot()
        try:
            p = self.ctx.coords.point("rune_ruins", "pick_row_1")
            x, y = p.x, p.y
        except ValueError:
            x, y = 450, 1420
        orange = 0
        for dx in range(-120, 121, 40):
            b, g, r = img[y, max(0, min(img.shape[1] - 1, x + dx))]
            if int(r) > 180 and int(g) > 100 and int(b) < 120:
                orange += 1
        return orange if orange else None

    def _open_rune_ruins(self) -> bool:
        if self._rune_ruins_brown_background():
            return True
        if not self._opt("nav", "trophy", settle=1.2, money_check=False):
            return False
        if not self._opt("rune_ruins", "entry", settle=1.2, money_check=False):
            log.warning("  Could not open Rune Ruins (calibrate rune_ruins.entry)")
            return False
        if not self._opt("rune_ruins", "chest_right", settle=1.0, money_check=False):
            return False
        sleep(0.8)
        return self._rune_ruins_brown_background()

    def _rune_ruins_do_pick(self) -> bool:
        for slot in range(RUNE_RUINS_PICK_SLOTS):
            self.ctx.kill.check()
            col = slot % 3
            row = slot // 3
            x = 250 + col * 200
            y = 1360 + row * 100
            self._tap(x, y, settle=0.5)
            sleep(0.6)
            keys = self._rune_ruins_key_reward_count()
            if keys is not None and keys >= 2:
                log.info("  pick %d: ~%d key reward -> reset", slot + 1, keys)
                self._opt("rune_ruins", "confirm_pick", settle=0.8, money_check=False)
                self._opt("rune_ruins", "dismiss_rewards", settle=0.5, money_check=False)
                return True
        log.warning("  Did not find 2-key reward in 9 picks")
        return False

    def claim_rune_ruins(self) -> None:
        keys_budget = self.rune_ruins_keys
        if not keys_budget or keys_budget <= 0:
            log.warning("-> Rune Ruins: specify --rune-ruins-keys N (multiple of 5)")
            return
        opens = keys_budget // RUNE_RUINS_KEYS_PER_X5
        if opens * RUNE_RUINS_KEYS_PER_X5 != keys_budget:
            log.warning("  Keys %d is not a multiple of %d; using %d x5", keys_budget, RUNE_RUINS_KEYS_PER_X5, opens)
        log.info("-> Rune Ruins (%d keys, %d x5)", keys_budget, opens)
        completed = 0
        for n in range(opens):
            log.info("  x5 %d/%d", n + 1, opens)
            if not self._open_rune_ruins():
                break
            if not self._opt("rune_ruins", "x5_open", settle=1.0, money_check=False):
                break
            sleep(0.8)
            if self._rune_ruins_do_pick():
                completed += 1
            else:
                break
        self._go_campaign()
        if completed > 0:
            self._finish_claim("rune_ruins")
        else:
            log.warning("Rune Ruins: 0 picks completed; not marking verified")

    def claim_trophy(self) -> None:
        log.info("-> Trophy / Collectibles")
        if not self._opt("nav", "trophy", settle=1.2, money_check=False):
            return
        self._opt("trophy", "codex", settle=0.8, money_check=False)
        self._dismiss_reward_popup(2)
        self._opt("trophy", "wish", settle=0.8, money_check=False)
        self._dismiss_reward_popup(2)
        self._go_campaign()
