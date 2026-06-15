"""Path diario: loop principal de claims free.

Loop principal (sin Friends):
  popups -> shop -> events -> great_value -> privilege -> messages ->
  guild -> hunt -> sidebar_events (island, angler, campaign_rout)

Coordenadas en espacio retrato 900x1600 (mismo que screenshot y tap ADB).
"""
from __future__ import annotations

import time

from .. import vision
from ..combat import CombatRunner
from ..daily_checks import DailyChecks, has_red_badge
from ..device import sleep
from ..failsafes import MoneyBlocked, StopRequested
from ..log import get_logger
from ..screens import ScreenId, is_lobby
from .base import BotContext

log = get_logger("daily")

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
ARENA_FALLBACK_OPPONENT_INDEX = 4
ARENA_REFRESH_BEFORE_FALLBACK = 3
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
GUILD_LEGACY_DONATIONS = 5
# Región del popup Legacy donde aparece "Ongoing guild tech donations" (loading).
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
    "task_center",
    "friends",
    "camp",
    "trophy",
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
    "peak_arena": "arena",
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
    ) -> None:
        self.ctx = ctx
        self.checks = DailyChecks(force=force)
        self.combat = CombatRunner(ctx, battle_timeout=180.0, dodge=False)
        if recover_ldplayer is not None:
            recover_emulator = recover_ldplayer
        self.recover_emulator = recover_emulator
        self._emulator_recovery_used = False
        self.arena_fights = arena_fights if arena_fights is not None else ARENA_FIGHTS

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
                raise ValueError(f"Claim desconocido: {raw!r}. Válidos: {valid}")
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
        return self._is_arena_opponents_popup() or self._is_events_hub()

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
        log.info("Claims a ejecutar: %s", ", ".join(selected))
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
                log.error("Claim falló (%s): %s", name, exc)
        log.info("Claims completados (%d).", len(selected))

    def run_one(self, name: str) -> None:
        self.run([name])

    def mark_verified(self, name: str) -> None:
        self.checks.mark_verified(name)

    def ensure_campaign_lobby(self) -> bool:
        from ..navigation import ensure_game_lobby

        return ensure_game_lobby(self.ctx, exit_combat=True)

    def _claim_handler(self, name: str):
        handlers = {
            "popups": self.claim_popups,
            "shop": self.claim_shop,
            "events": self.claim_events,
            "gold_cave": self.claim_gold_cave,
            "shackled_jungle": self.claim_shackled_jungle,
            "abyssal_tide": self.claim_abyssal_tide,
            "arena": self.claim_arena,
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
        }
        return handlers[name]

    def _opt(self, section: str, key: str, settle: float = 0.8, money_check: bool = True) -> bool:
        try:
            self.ctx.tap_point(section, key, money_check=money_check, settle=settle)
            return True
        except ValueError as exc:
            log.warning("Paso omitido %s.%s: %s", section, key, exc)
            return False
        except MoneyBlocked as exc:
            log.warning("Paso bloqueado por MoneyGuard %s.%s: %s", section, key, exc)
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
            log.info("  Sin cambio visible tras %s.%s; asumo no disponible", section, key)
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
        log.info("-> Cerrar popups iniciales")
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
            log.warning("Shop tenía badge pero no pude confirmar ningún free; no marco verificado")

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
                log.warning("Shackled Jungle: 0 runs completados; no marco como verificado")
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
                log.warning("Abyssal Tide: 0 runs completados; no marco como verificado")
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
        if vision.difference(before, after) > 0.015:
            log.info(
                "  Events: pantalla cambió (%s); continúo hacia Dungeon",
                self.ctx.current_screen().value,
            )
            return True
        log.warning(
            "  No se confirmó pantalla Events (quedó en %s)",
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
        # Título "Abyssal Tide" arriba-izq (Refresh en skill select no lo tiene)
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
        self._run_arena_fights("peak_arena", fights=ARENA_FIGHTS)

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
            log.info("    Quick Raid 1 sin rewards; corto")
            self._opt("menu", "close_x", settle=0.6, money_check=False)
            return

        for n in range(2, GOLD_CAVE_QUICK_RAIDS + 1):
            log.info("    Quick Raid %d/%d (doble tap: habilita ticket + raid)", n, GOLD_CAVE_QUICK_RAIDS)
            if not self._gold_cave_raid_cycle(quick_raid_taps=2):
                log.info("    Sin más Quick Raids")
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
        log.info("  Scroll lista Dungeon hacia Shackled Jungle")
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
        log.info("  Saliendo de Shackled Jungle -> lobby campaña")
        for _ in range(10):
            self.ctx.kill.check()
            img = self.ctx.device.screenshot()
            sid = self.ctx.current_screen()
            if is_lobby(img):
                log.info("  Lobby de campaña alcanzado")
                return
            if sid in DUNGEON_COMBAT:
                if needs_post_run_dismiss(img):
                    log.info("  Cerrando post-run Shackled Jungle")
                    dismiss_shackled_challenge_end(self.ctx)
                    sleep(0.8)
                elif self._resume_shackled_combat():
                    continue
                else:
                    sleep(0.5)
                continue
            if event_challenge_end(img) or needs_post_run_dismiss(img):
                log.info("  Cerrando pantalla Challenge has ended")
                dismiss_shackled_challenge_end(self.ctx)
                sleep(0.8)
                continue
            if self._is_shackled_jungle_popup_screen(img):
                log.info("  Back desde popup Shackled Jungle")
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
            log.warning("  No se confirmó lobby tras salir de Shackled Jungle")
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
            log.warning("    Start ignorado: no estamos en popup Shackled Jungle")
            return False
        if use_ad_ticket:
            log.info("    ticket ad -> seleccionar entrada + doble Start")
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
                log.info("    Start sin respuesta; reintento con ticket ad + doble Start")
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
        log.info("    resultado: %s", result)
        if not self._shackled_run_counted(result):
            return False
        if not dungeon_combat.collect_event_end():
            log.warning("    post-run Shackled no cerrado")
            return False
        sleep(0.8)
        return True

    def _events_shackled_jungle(self, *, resume: bool = False, from_popup: bool = False) -> int:
        log.info("  Shackled Jungle (hasta %d oportunidades, solo skills, sin movimiento)", SHACKLED_JUNGLE_RUNS)

        dungeon_combat = CombatRunner(
            self.ctx,
            battle_timeout=SHACKLED_JUNGLE_BATTLE_TIMEOUT,
            dodge=False,
            skills_only=True,
        )

        completed = 0
        runs_left = SHACKLED_JUNGLE_RUNS
        self.ctx.hold_combat = True
        try:
            if resume or self._is_shackled_combat_active():
                log.info("    retomando combate en curso")
                if self._run_one_shackled(dungeon_combat):
                    completed += 1
                runs_left -= 1
                if runs_left <= 0:
                    return completed

            if from_popup or self._is_shackled_jungle_popup():
                pass
            elif not self._open_shackled_jungle_popup():
                log.warning("  No se abrió popup Shackled Jungle")
                return completed

            for n in range(runs_left):
                run_num = SHACKLED_JUNGLE_RUNS - runs_left + n + 1
                log.info("    run %d/%d", run_num, SHACKLED_JUNGLE_RUNS)
                if not self._start_shackled_jungle_run(use_ad_ticket=False):
                    log.info("    Start no disponible; corto")
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
        log.info("  Scroll lista Dungeon hacia Abyssal Tide")
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
        log.info("  Retomando combate Shackled Jungle")
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
        log.info("  Retomando combate Abyssal Tide")
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
        log.info("  Saliendo de Abyssal Tide -> lobby campaña")
        for _ in range(10):
            self.ctx.kill.check()
            img = self.ctx.device.screenshot()
            sid = self.ctx.current_screen()
            if is_lobby(img):
                log.info("  Lobby de campaña alcanzado")
                return
            if sid in DUNGEON_COMBAT:
                if needs_post_run_dismiss(img):
                    log.info("  Cerrando post-run Abyssal Tide")
                    dismiss_shackled_challenge_end(self.ctx)
                    sleep(0.8)
                elif self._resume_abyssal_combat():
                    continue
                else:
                    sleep(0.5)
                continue
            if event_challenge_end(img) or needs_post_run_dismiss(img):
                log.info("  Cerrando pantalla Challenge has ended")
                dismiss_shackled_challenge_end(self.ctx)
                sleep(0.8)
                continue
            if self._is_abyssal_tide_popup_screen(img):
                log.info("  Back desde popup Abyssal Tide")
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
            log.warning("  No se confirmó lobby tras salir de Abyssal Tide")
            self.ensure_campaign_lobby()

    def _start_abyssal_tide_run(self, *, use_ad_ticket: bool = False) -> bool:
        if not self._is_abyssal_tide_popup():
            log.warning("    Start ignorado: no estamos en popup Abyssal Tide")
            return False
        if use_ad_ticket:
            log.info("    ticket ad -> seleccionar entrada + doble Start")
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
                log.info("    Start sin respuesta; reintento con ticket ad + doble Start")
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
        log.info("    resultado: %s", result)
        if not self._abyssal_run_counted(result):
            return False
        if not dungeon_combat.collect_event_end():
            log.warning("    post-run Abyssal no cerrado")
            return False
        sleep(0.8)
        return True

    def _events_abyssal_tide(self, *, resume: bool = False, from_popup: bool = False) -> int:
        log.info("  Abyssal Tide (hasta %d free + ad si visible, AFK)", ABYSSAL_TIDE_RUNS)

        dungeon_combat = CombatRunner(
            self.ctx,
            battle_timeout=ABYSSAL_TIDE_BATTLE_TIMEOUT,
            dodge=False,
            afk_only=True,
        )

        completed = 0
        runs_left = ABYSSAL_TIDE_RUNS
        self.ctx.hold_combat = True
        try:
            if resume or self._is_abyssal_combat_active():
                log.info("    retomando combate en curso")
                if self._run_one_abyssal(dungeon_combat):
                    completed += 1
                runs_left -= 1
                if runs_left <= 0 and not self._abyssal_ad_ticket_visible():
                    return completed

            if not (from_popup or self._is_abyssal_tide_popup()):
                if not self._open_abyssal_tide_popup():
                    log.warning("  No se abrió popup Abyssal Tide")
                    return completed

            for n in range(runs_left):
                run_num = ABYSSAL_TIDE_RUNS - runs_left + n + 1
                log.info("    run %d/%d (free)", run_num, ABYSSAL_TIDE_RUNS)
                if not self._start_abyssal_tide_run(use_ad_ticket=False):
                    log.info("    Start free no disponible; corto free runs")
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
        log.info("-> Events / Arena (%d peleas)", self.arena_fights)
        if not self._is_arena_opponents_popup() and not self._ensure_events_hub():
            return
        done = self._run_arena_fights("arena", fights=self.arena_fights)
        log.info("  Arena: %d/%d peleas", done, self.arena_fights)
        self._leave_arena_to_campaign()
        if done > 0:
            self._finish_claim("arena")
        else:
            log.warning("Arena: 0 peleas completadas; no marco como verificado")

    def _is_arena_opponents_popup(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        try:
            return vision.matches(
                img,
                "anchors/arena_opponents_popup.png",
                threshold=0.72,
                region=(300, 300, 260, 80),
            )
        except FileNotFoundError:
            return False

    def _open_arena_rivals_popup(self, banner_key: str) -> bool:
        if self._is_arena_opponents_popup():
            return True
        if not self._ensure_events_hub():
            return False
        self._opt("events", "tab_arena", settle=1.0, money_check=False)
        if not self._opt("events", banner_key, settle=1.5, money_check=False):
            return False
        sleep(0.8)
        if self._is_arena_opponents_popup():
            return True
        if not self._opt("events", "arena_challenge", settle=1.2, money_check=False):
            return False
        sleep(1.5)
        ok = self._is_arena_opponents_popup()
        if not ok:
            log.warning("  Popup de rivales Arena no detectado")
        return ok

    def _read_arena_opponent_power(self, index: int = ARENA_OPPONENT_INDEX) -> float | None:
        row_i = max(0, index - 1)
        return vision.read_arena_opponent_power(self.ctx.device.screenshot(), row_i)

    def _arena_row_tap_y(self, index: int = ARENA_OPPONENT_INDEX) -> int | None:
        rows = vision.find_arena_power_row_ys(self.ctx.device.screenshot())
        row_i = max(0, index - 1)
        if len(rows) <= row_i:
            return None
        return rows[row_i]

    def _arena_refresh_opponents(self) -> None:
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
        sleep(2.0)

    def _is_arena_victory_screen(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        try:
            if vision.matches(
                img,
                "anchors/arena_victory.png",
                threshold=0.68,
                region=(280, 350, 340, 200),
            ):
                return True
            if vision.matches(
                img,
                "anchors/arena_confirm.png",
                threshold=0.62,
                region=(220, 1330, 460, 180),
            ):
                return True
        except FileNotFoundError:
            pass
        return False

    def _tap_arena_confirm(self) -> None:
        self._opt("events", "arena_confirm", settle=1.5, money_check=False)

    def _wait_arena_victory_and_confirm(self) -> bool:
        deadline = time.monotonic() + ARENA_VICTORY_TIMEOUT
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            screen = self.ctx.device.screenshot()
            if self._is_arena_victory_screen(screen):
                log.info("  victoria arena -> Confirm")
                self._tap_arena_confirm()
                sleep(1.0)
                return True
            if self._is_arena_opponents_popup(screen):
                log.info("  popup rivales (fin arena)")
                return True
            sid = self.ctx.current_screen()
            log.info("  esperando fin arena (%s)...", sid.value)
            sleep(ARENA_VICTORY_POLL_S)
        log.warning("  timeout fin arena (%.0fs); intento salir combate", ARENA_VICTORY_TIMEOUT)
        if self.ctx.current_screen() == ScreenId.BATTLE:
            self._exit_battle()
        return self._is_arena_opponents_popup() or self._is_arena_victory_screen()

    def _arena_attack_opponent(self, index: int = ARENA_OPPONENT_INDEX) -> None:
        y = self._arena_row_tap_y(index)
        if y is None:
            self._opt("events", "arena_opponent_3", settle=0.6, money_check=False)
            return
        self._tap(800, y, settle=0.8)

    def _wait_for_battle_start(self, timeout: float = 18.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            if self.ctx.current_screen() == ScreenId.BATTLE:
                return True
            sleep(0.35)
        return False

    def _wait_arena_opponents(self, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.ctx.kill.check()
            if self._is_arena_opponents_popup():
                return True
            sleep(0.35)
        return False

    def _arena_pick_opponent_once(self, banner_key: str = "arena_banner") -> bool:
        target = ARENA_OPPONENT_INDEX
        for refresh_i in range(ARENA_REFRESH_BEFORE_FALLBACK):
            power = self._read_arena_opponent_power(ARENA_OPPONENT_INDEX)
            log.info("  rival #%d poder=%s", ARENA_OPPONENT_INDEX, f"{power:.2f}M" if power else "?")
            if power is not None and power < ARENA_POWER_THRESHOLD_M:
                target = ARENA_OPPONENT_INDEX
                break
            log.info("  refresh %d/%d", refresh_i + 1, ARENA_REFRESH_BEFORE_FALLBACK)
            self._arena_refresh_opponents()
        else:
            target = ARENA_FALLBACK_OPPONENT_INDEX
            power4 = self._read_arena_opponent_power(ARENA_FALLBACK_OPPONENT_INDEX)
            log.info(
                "  rival #%d sigue fuerte -> ataco rival #%d (poder=%s)",
                ARENA_OPPONENT_INDEX,
                target,
                f"{power4:.2f}M" if power4 else "?",
            )

        log.info("  atacar rival #%d", target)
        self._arena_attack_opponent(target)
        sleep(1.0)
        if not self._wait_for_battle_start(timeout=20.0):
            if self._is_arena_victory_screen():
                self._tap_arena_confirm()
            elif not self._wait_arena_victory_and_confirm():
                log.warning("  no entró combate ni victoria tras tap rival")
                return False
            if self._wait_arena_opponents(timeout=25):
                return True
            return self._open_arena_rivals_popup(banner_key)

        if not self._wait_arena_victory_and_confirm():
            log.warning("  no se cerró victoria arena")
            if self._is_arena_victory_screen():
                self._tap_arena_confirm()

        if not self._wait_arena_opponents(timeout=30):
            log.warning("  no volvió popup rivales tras confirm")
            if not self._open_arena_rivals_popup(banner_key):
                return False
        return True

    def _run_arena_fights(self, mode: str, *, fights: int) -> int:
        banner = "arena_banner" if mode == "arena" else "peak_arena_banner"
        log.info("  %s (%d peleas)", mode, fights)
        if not self._open_arena_rivals_popup(banner):
            return 0

        completed = 0
        for n in range(fights):
            log.info("    pelea %d/%d", n + 1, fights)
            if self._is_arena_victory_screen():
                log.info("  victoria pendiente -> Confirm")
                self._tap_arena_confirm()
                sleep(1.0)
            if not self._is_arena_opponents_popup():
                if not self._open_arena_rivals_popup(banner):
                    break
            if self._arena_pick_opponent_once(banner):
                completed += 1
            else:
                break
            sleep(0.8)
        return completed

    def _leave_arena_to_campaign(self) -> None:
        if self._is_arena_opponents_popup():
            self._back()
            sleep(0.8)
        self._back()
        sleep(0.6)
        self._go_campaign()

    def _events_arena_mode(self, mode: str, *, fights: int) -> None:
        self._run_arena_fights(mode, fights=fights)

    def _pick_arena_opponent(self) -> None:
        self._arena_pick_opponent_once()

    def claim_great_value(self) -> None:
        log.info("-> Great Value")
        if not self._lobby_badge("lobby", "great_value"):
            log.info("Sin badge en Great Value; omito")
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
            log.warning("Great Value abrió pero no pude confirmar free; no marco verificado")

    def claim_privilege(self) -> None:
        log.info("-> Privilege Card")
        if not self._lobby_badge("lobby", "privilege_card"):
            log.info("Sin badge en Privilege; omito")
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
            log.info("Sin badge en Messages; omito")
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
                log.info("    Bargain sin popup (ya hecho o loading)")
        else:
            log.info("    Sin badge en Bargain; omito (Purchase cuesta gemas)")
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
            "%s — reiniciando emulador (unico recovery automatico por sesion)...",
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
        log.warning("Legacy loading colgado (>%.0fs)", timeout)
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
        log.warning("Legacy donate sin respuesta en pantalla")
        return False

    def _guild_hall_legacy(self, *, _after_recovery: bool = False) -> None:
        log.info("  Guild Hall -> Research -> Legacy (5 donaciones: Free, 20, 40, 60, 80)")
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
            if not _after_recovery and self._try_ldplayer_recovery("Legacy loading al abrir"):
                log.info("  Reintentando Legacy tras reboot LDPlayer...")
                if self._opt("lobby", "guild", settle=2.5):
                    sleep(1.5)
                    return self._guild_hall_legacy(_after_recovery=True)
            log.info("    Legacy bloqueado; omito donaciones")
            self._opt("menu", "close_x", settle=0.6, money_check=False)
            self._back()
            self._back()
            return

        done = 0
        for n in range(GUILD_LEGACY_DONATIONS):
            log.info("    Legacy donate %d/%d", n + 1, GUILD_LEGACY_DONATIONS)
            if not self._guild_legacy_donate_once():
                if not _after_recovery and self._try_ldplayer_recovery("Legacy donate sin respuesta"):
                    log.info("  Reintentando Legacy tras reboot LDPlayer...")
                    if self._opt("lobby", "guild", settle=2.5):
                        sleep(1.5)
                        return self._guild_hall_legacy(_after_recovery=True)
                log.info("    No quedan donaciones o loading bloqueó")
                break
            done += 1

        log.info("    Legacy donaciones completadas: %d/%d", done, GUILD_LEGACY_DONATIONS)
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
            log.info("    Sin badge en Schedule; omito")
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
            log.info("  Hunt claim: espero rewards y cierro overlay inferior")
            self._hunt_dismiss_rewards(wait_s=2.0)
            touched = True
        if self._opt("hunt", "quick_hunt", settle=1.2, money_check=False):
            free_chances = self._hunt_quick_chances("quick_free")
            if free_chances is None:
                free_chances = 2 if self._hunt_quick_available("quick_free") else 0
            log.info("  Quick Hunt free chances: %s", free_chances)
            for _ in range(min(2, max(0, free_chances))):
                if free_chances is None and not self._hunt_quick_available("quick_free"):
                    log.info("  Quick Hunt: sin free diario/ticket visible en quick_free; no toco")
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
            log.info("  Quick Hunt x5 chances: %s", x5_chances if x5_chances is not None else "(no legible)")
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
            log.warning("Hunt abrió pero no confirmó rewards; no marco verificado")

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
                log.info("Sin badge en %s; omito", claim_id)
                continue
            if handler() is False:
                log.warning("%s no completó pasos mínimos; no marco verificado", claim_id)
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
        log.info("-> Friends (Claim & Gift All) — fuera del loop principal")
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

    def claim_trophy(self) -> None:
        log.info("-> Trophy / Collectibles")
        if not self._opt("nav", "trophy", settle=1.2, money_check=False):
            return
        self._opt("trophy", "codex", settle=0.8, money_check=False)
        self._dismiss_reward_popup(2)
        self._opt("trophy", "wish", settle=0.8, money_check=False)
        self._dismiss_reward_popup(2)
        self._go_campaign()
