"""Path diario: loop principal de claims free.

Loop principal (sin Friends):
  popups -> shop -> events -> great_value -> privilege -> messages ->
  guild -> hunt -> sidebar_events (island, angler, campaign_rout)

Coordenadas en espacio retrato 900x1600 (mismo que screenshot y tap ADB).
"""
from __future__ import annotations

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
GOLD_CAVE_QUICK_RAIDS = 3
SHACKLED_JUNGLE_RUNS = 2
SHACKLED_JUNGLE_BATTLE_TIMEOUT = 600.0
SHACKLED_COMBAT = frozenset({
    ScreenId.BATTLE,
    ScreenId.SKILL_SELECT,
    ScreenId.ROULETTE,
    ScreenId.DEVIL_DEAL,
})
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
    ) -> None:
        self.ctx = ctx
        self.checks = DailyChecks(force=force)
        self.combat = CombatRunner(ctx, battle_timeout=180.0, dodge=False)
        if recover_ldplayer is not None:
            recover_emulator = recover_ldplayer
        self.recover_emulator = recover_emulator
        self._emulator_recovery_used = False

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

    def _skip_lobby_for_shackled(self) -> bool:
        return self._is_shackled_jungle_popup() or self._is_shackled_combat_active()

    def run(self, claims: list[str] | None = None) -> None:
        selected = self.resolve_claims(claims)
        if not (len(selected) == 1 and selected[0] == "shackled_jungle" and self._skip_lobby_for_shackled()):
            self.ensure_campaign_lobby()
        log.info("Claims a ejecutar: %s", ", ".join(selected))
        for name in selected:
            if not self.checks.should_run(name):
                continue
            if not (name == "shackled_jungle" and self._skip_lobby_for_shackled()):
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
        from ..navigation import ensure_campaign_lobby

        return ensure_campaign_lobby(self.ctx, exit_combat=True)

    def _claim_handler(self, name: str):
        handlers = {
            "popups": self.claim_popups,
            "shop": self.claim_shop,
            "events": self.claim_events,
            "gold_cave": self.claim_gold_cave,
            "shackled_jungle": self.claim_shackled_jungle,
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
        return has_red_badge(self.ctx.device.screenshot(), p.x, p.y)

    def _shop_tab_badge(self, tab_key: str) -> bool:
        try:
            p = self.ctx.coords.point("shop", tab_key)
        except (KeyError, ValueError):
            return False
        return has_red_badge(self.ctx.device.screenshot(), p.x, p.y)

    def _claim_all_generic(self, section: str, key: str = "claim_all") -> None:
        if self._opt(section, key, settle=0.8, money_check=False):
            self._dismiss_reward_popup(2)

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
        log.info("-> Shop (Gear Chest, Limited Offer, Top Up, Wish)")
        if not self._opt("nav", "shop", settle=1.5):
            return

        if self._shop_tab_badge("tab_gear_chest") or self.checks.force:
            self._opt("shop", "tab_gear_chest", settle=0.8, money_check=False)
            self._opt("shop", "gear_draw_x10", settle=1.0, money_check=False)
            self._dismiss_reward_popup(3)
        else:
            log.info("Gear Chest sin badge; intento draw igual por si quedó sin exclamación")
            if self._opt("shop", "tab_gear_chest", settle=0.8, money_check=False):
                self._opt("shop", "gear_draw_x10", settle=1.0, money_check=False)
                self._dismiss_reward_popup(3)

        if self._shop_tab_badge("tab_limited_offer"):
            self._opt("shop", "tab_limited_offer", settle=0.8, money_check=False)
            self._opt("shop", "limited_offer_free", settle=0.8, money_check=False)
            self._dismiss_reward_popup(2)

        if self._shop_tab_badge("tab_top_up"):
            self._opt("shop", "tab_top_up", settle=0.8, money_check=False)
            self._opt("shop", "top_up_sub_gold", settle=0.8, money_check=False)
            self._opt("shop", "top_up_free", settle=0.8, money_check=False)
            self._dismiss_reward_popup(2)

        if self._shop_tab_badge("tab_wish"):
            self._opt("shop", "tab_wish", settle=0.8, money_check=False)
            self._opt("shop", "wish_free", settle=0.8, money_check=False)
            self._dismiss_reward_popup(2)

        self._go_campaign()
        self._finish_claim("shop")

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

    def _events_subtab_highlighted(self, screen, x: int) -> bool:
        b, g, r = screen[1380, x]
        return int(g) > 150 and (int(b) > 200 or int(r) > 200)

    def _is_events_hub(self, screen=None) -> bool:
        img = screen if screen is not None else self.ctx.device.screenshot()
        if is_lobby(img):
            return False
        if self._is_shackled_jungle_popup_screen(img):
            return True
        return any(self._events_subtab_highlighted(img, x) for x in (180, 450, 680))

    def _ensure_events_hub(self) -> bool:
        if self._is_shackled_jungle_popup() or self._is_events_hub():
            return True
        if not self.ensure_campaign_lobby():
            log.warning("  No se llegó al lobby antes de Events")
            return False
        before = self.ctx.device.screenshot()
        if not self._opt("nav", "events", settle=1.5, money_check=False):
            return False
        after = self.ctx.device.screenshot()
        if self._is_events_hub(after) or self._is_shackled_jungle_popup_screen(after):
            return True
        if vision.difference(before, after) <= 0.015:
            log.warning("  Tap Events sin cambio de pantalla; reintento")
            self._opt("nav", "events", settle=1.5, money_check=False)
            after = self.ctx.device.screenshot()
        ok = self._is_events_hub(after) or self._is_shackled_jungle_popup_screen(after)
        if not ok:
            log.warning("  No se confirmó pantalla Events (quedó en %s)", self.ctx.current_screen().value)
        return ok

    def _is_shackled_jungle_popup_screen(self, screen) -> bool:
        if is_lobby(screen):
            return False
        b, g, r = screen[1264, 450]
        if not (int(r) > 200 and int(g) > 150):
            return False
        if self._events_subtab_highlighted(screen, 680):
            return False
        return True

    def _is_shackled_jungle_popup(self) -> bool:
        return self._is_shackled_jungle_popup_screen(self.ctx.device.screenshot())

    def claim_events(self) -> None:
        log.info("-> Events (Gold Cave + Arena + Peak Arena)")
        if not self._opt("nav", "events", settle=1.5):
            return

        self._events_gold_cave()
        self._events_arena_mode("arena", fights=ARENA_FIGHTS)
        self._events_arena_mode("peak_arena", fights=ARENA_FIGHTS)

        self._go_campaign()
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
        return self.ctx.current_screen() in SHACKLED_COMBAT

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
        from ..combat_prompts import dismiss_shackled_challenge_end, is_shackled_challenge_end

        if is_lobby(self.ctx.device.screenshot()):
            return
        log.info("  Saliendo de Shackled Jungle -> lobby campaña")
        for _ in range(8):
            self.ctx.kill.check()
            img = self.ctx.device.screenshot()
            if is_lobby(img):
                log.info("  Lobby de campaña alcanzado")
                return
            if is_shackled_challenge_end(img):
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
            sid = self.ctx.current_screen()
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
        dungeon_combat.collect_event_end()
        sleep(0.8)
        return self._shackled_run_counted(result)

    def _events_shackled_jungle(self, *, resume: bool = False, from_popup: bool = False) -> int:
        log.info("  Shackled Jungle (%d runs, solo skills, sin movimiento)", SHACKLED_JUNGLE_RUNS)

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
                use_ad = run_num >= 2
                if not self._start_shackled_jungle_run(use_ad_ticket=use_ad):
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

    def _events_arena_mode(self, mode: str, *, fights: int) -> None:
        banner = "arena_banner" if mode == "arena" else "peak_arena_banner"
        log.info("  %s (%d peleas)", mode, fights)
        self._opt("events", "tab_arena", settle=1.0, money_check=False)
        if not self._opt("events", banner, settle=1.5, money_check=False):
            return

        for n in range(fights):
            log.info("    pelea %d/%d", n + 1, fights)
            if not self._opt("events", "arena_challenge", settle=1.0, money_check=False):
                break
            self._pick_arena_opponent()
            result = self.combat.run_until_end()
            log.info("    resultado: %s", result)
            self.combat.collect_end()
            sleep(1.0)

        self._back()

    def _pick_arena_opponent(self) -> None:
        """Elige oponente: intenta filas medias (600-900 aprox) y cae al primero."""
        rows = (520, 680, 840, 400)
        for y in rows:
            self._tap(750, y, settle=0.8)
            sid = self.ctx.current_screen()
            if sid in (ScreenId.BATTLE, ScreenId.ROULETTE, ScreenId.SKILL_SELECT):
                return
        self._tap(750, 680, settle=0.8)

    def claim_great_value(self) -> None:
        log.info("-> Great Value")
        if not self._lobby_badge("lobby", "great_value"):
            log.info("Sin badge en Great Value; omito")
            return
        if not self._opt("lobby", "great_value", settle=1.2, money_check=False):
            return
        self._opt("great_value", "free_bonus", settle=0.8, money_check=False)
        self._dismiss_reward_popup(2)
        self._back()
        self._finish_claim("great_value")

    def claim_privilege(self) -> None:
        log.info("-> Privilege Card")
        if not self._lobby_badge("lobby", "privilege_card"):
            log.info("Sin badge en Privilege; omito")
            return
        if not self._opt("lobby", "privilege_card", settle=1.2, money_check=False):
            return
        self._claim_all_generic("privilege")
        self._back()
        self._finish_claim("privilege")

    def claim_messages(self) -> None:
        log.info("-> Messages")
        has_mail = self._lobby_badge("lobby", "messages")
        try:
            has_mail = has_mail or vision.matches(
                self.ctx.device.screenshot(), MESSAGES_ICON, threshold=0.72
            )
        except FileNotFoundError:
            pass
        if not has_mail:
            log.info("Sin badge/icono de Messages; omito")
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

    def claim_hunt(self) -> None:
        log.info("-> Hunt (Claim + Quick Hunt free + x5)")
        if not self._opt("lobby", "hunt", settle=1.2, money_check=False):
            return
        if self._opt("hunt", "claim", settle=0.8, money_check=False):
            self._dismiss_reward_popup(3)
        if self._opt("hunt", "quick_hunt", settle=0.8, money_check=False):
            self._opt("hunt", "quick_free", settle=0.6, money_check=False)
            self._dismiss_reward_popup(2)
            self._opt("hunt", "quick_x5", settle=0.6, money_check=False)
            self._dismiss_reward_popup(2)
            self._opt("menu", "close_x", settle=0.4, money_check=False)
        self._opt("hunt", "close_popup", settle=0.4, money_check=False)
        self._finish_claim("hunt")

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
            handler()
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

    def claim_island_treasure(self) -> None:
        log.info("-> Island Treasure")
        if not self._opt("lobby", "island_treasure", settle=1.2):
            return
        if self._opt("island_treasure", "pack_tab", settle=1.0):
            self._opt("island_treasure", "pack1_free", settle=0.8)
            self._dismiss_reward_popup(1)
            self._opt("island_treasure", "pack2_free", settle=0.8)
            self._dismiss_reward_popup(1)
        self._back()

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
