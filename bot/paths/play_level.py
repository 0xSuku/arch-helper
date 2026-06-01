"""Path de juego: jugar N partidas de un nivel (por defecto 50).

Flujo: lobby -> selección de nivel -> entrar ->
bucle de combate (esquivar con swipes + elegir skills) -> fin de run ->
recoger recompensas -> volver al lobby -> repetir.
"""
from __future__ import annotations

import time

from .. import screens, vision
from ..device import sleep
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

_IN_COMBAT_SCREENS = frozenset(
    {
        ScreenId.BATTLE,
        ScreenId.SKILL_SELECT,
        ScreenId.ROULETTE,
        ScreenId.DEVIL_DEAL,
    }
)


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
    ) -> None:
        self.ctx = ctx
        self.level = level
        self.dodge = dodge
        self.skills_only = skills_only
        # games=None -> jugar hasta agotar energía (modo farmeo).
        self.games = games
        self.until_no_energy = games is None
        self.battle_timeout = battle_timeout
        self.max_games = max_games
        self.start_timeout = start_timeout
        # forever -> al quedarse sin energía, espera y reintenta indefinidamente.
        self.forever = forever
        self.energy_wait_s = energy_wait_s
        self.picker = SkillPicker()
        if self.until_no_energy:
            from ..run_end_dismiss import configure_farm_ctx

            configure_farm_ctx(ctx)

    def run(self) -> int:
        won = 0
        played = 0
        n = 0
        while True:
            if not self.forever:
                if not self.until_no_energy and n >= (self.games or 0):
                    break
                if self.until_no_energy and n >= self.max_games:
                    log.warning("Tope de seguridad de %d partidas alcanzado; corto.", self.max_games)
                    break

            self.ctx.kill.check()
            if self.forever:
                etiqueta = f"{n + 1} (infinito)"
            elif self.until_no_energy:
                etiqueta = f"{n + 1} (farmeo energía)"
            else:
                etiqueta = f"{n + 1}/{self.games}"
            log.info("=== Partida %s (nivel %d) ===", etiqueta, self.level)

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
                        log.info("Reconecto: post-run activo (%s); recojo y reinicio.", sid.value)
                    else:
                        log.info("Reconecto: partida ya finalizada (%s); recojo y reinicio.", sid.value)
                    self._collect_run_end()
                    continue

                if in_combat and not is_post_run_overlay(screen):
                    log.info("Reconecto a una partida en curso (%s)", sid.value)
                else:
                    if not self._enter_level():
                        self._abort_start()
                        if self.forever:
                            log.info(
                                "Sin energía o nivel 50 no confirmado; espero %.0f min y reintento.",
                                self.energy_wait_s / 60.0,
                            )
                            self._interruptible_sleep(self.energy_wait_s)
                            continue
                        log.info("No se pudo iniciar la partida (energía agotada o sin nivel). Fin.")
                        break

                result = self._fight()
                log.info("Resultado: %s", result)
                if result == "victory":
                    won += 1
                if not self._collect_run_end():
                    sid = self.ctx.current_screen()
                    from ..run_end_dismiss import is_challenge_ended_screen

                    if sid in _IN_COMBAT_SCREENS and not is_challenge_ended_screen(
                        self.ctx.device.screenshot()
                    ):
                        log.warning("Falso fin de partida (%s); reanudo combate", sid.value)
                        if result == "victory":
                            won -= 1
                        result = self._fight()
                        log.info("Resultado (reanudado): %s", result)
                        if result == "victory":
                            won += 1
                        self._collect_run_end()
                played += 1
            except StopRequested:
                raise
            except (PathAborted, ValueError, KeyError) as exc:
                log.error("Partida abortada: %s", exc)
                dump_screen(self.ctx.device, "play_aborted")
                self.ctx.return_to_lobby()
            n += 1

        log.info("Terminado: %d partida(s) jugada(s), %d victoria(s).", played, won)
        return won

    def _interruptible_sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.ctx.kill.check()
            sleep(min(5.0, max(0.1, end - time.time())))

    def _enter_level(self) -> bool:
        """Asegura el nivel 50 seleccionado, presiona Start y confirma combate.
        Nunca arranca si no puede confirmar el nivel 50 (evita jugar otro nivel)."""
        if self.ctx.current_screen() != ScreenId.LOBBY:
            if not self.ctx.return_to_lobby():
                log.warning("No se confirmó lobby antes de entrar al nivel")

        if not self._ensure_level_50():
            log.warning("No se pudo confirmar el nivel 50; no presiono Start.")
            return False

        self.ctx.tap_point("lobby", "campaign_start", money_check=True, settle=0.0)
        return self._wait_combat_start()

    def _level_50_visible(self) -> bool:
        try:
            return vision.matches(
                self.ctx.device.screenshot(), LEVEL50_TEMPLATE, threshold=LEVEL_TITLE_THRESHOLD
            )
        except FileNotFoundError:
            log.warning("Falta templates/%s; no puedo verificar el nivel 50.", LEVEL50_TEMPLATE)
            return False

    def _ensure_level_50(self) -> bool:
        """Verifica que el nivel 50 esté centrado. Si no, navega según el piso actual."""
        if self._level_50_visible():
            return True
        log.info("Nivel 50 no visible; navegando el mapa de campaña...")

        current = self._read_campaign_floor()
        if current is not None:
            log.info("Piso actual en mapa: %d (objetivo %d)", current, self.level)
            if current == self.level:
                return self._fine_tune_level_50()
            if current < self.level:
                return self._scroll_toward_level(direction="up")
            return self._scroll_toward_level(direction="down")

        log.info("Piso no legible; subo desde la posición actual...")
        if self._scroll_toward_level(direction="up"):
            return True
        log.info("No encontrado subiendo; bajo desde la posición actual...")
        if self._scroll_toward_level(direction="down"):
            return True

        log.info("Rescan completo desde piso 1...")
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
        """El badge dice 50 pero el título no matchea; nudge corto en ambas direcciones."""
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
            log.warning("Badge en piso %d pero título del nivel 50 no confirmado", self.level)
        return ok

    def _swipe_higher_floor(self) -> None:
        """Sube el número de piso (49 -> 50)."""
        self.ctx.device.swipe(450, 550, 450, 950, 600)

    def _swipe_lower_floor(self) -> None:
        """Baja el número de piso (50 -> 49)."""
        self.ctx.device.swipe(450, 950, 450, 550, 600)

    def _scroll_to_lowest_floor(self, max_swipes: int = 90) -> None:
        """Swipe hasta el piso 1 (fondo del mapa)."""
        prev = None
        for _ in range(max_swipes):
            self.ctx.kill.check()
            screen = self.ctx.device.screenshot()
            if prev is not None and not vision.screen_changed(prev, screen, 0.008):
                log.info("Fondo del mapa de campaña alcanzado (piso 1)")
                return
            prev = screen
            self._swipe_lower_floor()
            sleep(0.25)
        log.warning("No se detectó el fondo del mapa tras %d swipes", max_swipes)

    def _scroll_toward_level(self, direction: str, max_swipes: int = 70) -> bool:
        swipe = self._swipe_higher_floor if direction == "up" else self._swipe_lower_floor
        label = "subiendo" if direction == "up" else "bajando"
        log.info("Buscando nivel %d (%s)...", self.level, label)
        stuck_reads = 0
        prev = None
        for _ in range(max_swipes):
            self.ctx.kill.check()
            if self._level_50_visible():
                log.info("Nivel %d localizado", self.level)
                return True
            swipe()
            sleep(0.3)
            screen = self.ctx.device.screenshot()
            if prev is not None and not vision.screen_changed(prev, screen, 0.008):
                stuck_reads += 1
                if stuck_reads >= 2:
                    log.info("Tope del mapa alcanzado (%s)", label)
                    return self._level_50_visible()
            else:
                stuck_reads = 0
            prev = screen
        ok = self._level_50_visible()
        if not ok:
            log.warning("No se ubicó el nivel %d tras %d swipes (%s)", self.level, max_swipes, label)
        return ok

    def _scroll_to_bottom(self, max_swipes: int = 90) -> None:
        self._scroll_to_lowest_floor(max_swipes=max_swipes)

    def _scroll_until_level_50(self, max_swipes: int = 70) -> bool:
        return self._scroll_toward_level(direction="up", max_swipes=max_swipes)

    def _wait_combat_start(self) -> bool:
        """Confirma inicio de combate. Si no aparece en start_timeout, asume
        que no se pudo entrar (energía agotada o popup de compra)."""
        deadline = time.time() + self.start_timeout
        while time.time() < deadline:
            self.ctx.kill.check()
            sid = self.ctx.current_screen()
            if sid in (
                ScreenId.BATTLE,
                ScreenId.ROULETTE,
                ScreenId.SKILL_SELECT,
                ScreenId.DEVIL_DEAL,
            ):
                log.info("Combate iniciado (%s)", sid.value)
                return True
            sleep(0.35)
        log.info("No se detectó inicio de combate en %.0fs", self.start_timeout)
        return False

    def _abort_start(self) -> None:
        """Cierra cualquier popup (p.ej. compra de energía) sin gastar y vuelve al lobby.
        Nunca confirma compras: solo back / cerrar."""
        self.ctx.back(settle=1.0)
        self.ctx.return_to_lobby()

    def _fight(self) -> str:
        if self.skills_only:
            return self._fight_skills_only()
        return self._fight_standard()

    def _fight_skills_only(self) -> str:
        """Shackled Jungle: solo elegir skills, idle entre level-ups."""
        from ..combat_prompts import find_reject_button, is_shackled_challenge_end

        timeout = BattleTimeout(self.battle_timeout)

        while True:
            self.ctx.kill.check()
            if timeout.expired():
                log.warning("BattleTimeout (%.0fs) alcanzado", self.battle_timeout)
                return "timeout"

            screen = self.ctx.device.screenshot()

            if is_shackled_challenge_end(screen):
                return "defeat"

            if find_reject_button(screen) is not None:
                self._handle_pact_reject(screen)
                continue

            sid = screens.identify_combat(screen)

            if sid == ScreenId.SKILL_SELECT:
                self._pick_skill_skills_only(screen)
                continue
            if sid == ScreenId.DEVIL_DEAL:
                self._handle_devil_deal()
                continue
            if sid == ScreenId.VICTORY:
                return "victory"
            if sid == ScreenId.DEFEAT:
                return "defeat"
            if sid == ScreenId.ROULETTE:
                self._handle_roulette()
                continue
            if sid == ScreenId.BATTLE:
                sleep(0.5)
                continue

            sleep(0.5)

    def _handle_pact_reject(self, screen) -> None:
        from ..combat_prompts import find_reject_button, scan_and_reject_coords

        coords = scan_and_reject_coords(screen) or find_reject_button(screen)
        if coords is None:
            return
        log.info("Pacto / activo detectado -> Reject @(%d,%d)", coords[0], coords[1])
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
        moved_up = False
        roulette_done = False

        while True:
            self.ctx.kill.check()
            if timeout.expired():
                log.warning("BattleTimeout (%.0fs) alcanzado", self.battle_timeout)
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
                        log.info("Post-run detectado (confirmado en battle) -> fin de partida")
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
                # Si la ruleta aún no apareció, nos movemos una vez hacia arriba
                # para pisarla/dispararla. Si ya se resolvió, no nos movemos.
                if not moved_up and not roulette_done:
                    self._grab_roulette()
                    moved_up = True
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
                    log.info("Post-run detectado (unknown) -> fin de partida")
                    return "victory"
                if unknown.update(True):
                    log.warning("Pantalla desconocida prolongada; intento avanzar/recuperar")
                    if self._looks_like_run_end():
                        return "ended"
                    idle_taps += 1
                    if idle_taps >= 3:
                        raise PathAborted("Pantalla desconocida persistente en combate")
                    unknown.reset()
                sleep(0.3)
                continue

            sleep(0.3)

    def _handle_roulette(self) -> None:
        """Pantalla de ruleta al inicio: pulsa Start, gira y toca para skip/reclamar
        hasta que vuelve al combate. Es gratis (no gasta gemas/dinero)."""
        log.info("Ruleta detectada: giro y reclamo")
        try:
            self.ctx.tap_point("roulette", "start", money_check=False, settle=0.0)
        except ValueError:
            self.ctx.tap(450, 1333, money_check=False, settle=0.0)
        sleep(0.35)
        try:
            skip = self.ctx.coords.point("roulette", "skip")
            sx, sy = skip.x, skip.y
        except ValueError:
            sx, sy = 450, 1000
        for _ in range(5):
            self.ctx.kill.check()
            if self.ctx.current_screen() != ScreenId.ROULETTE:
                log.info("Ruleta cerrada; sigo el combate")
                return
            self.ctx.tap(sx, sy, money_check=False, settle=0.0)
            if self.ctx.wait_until_not(ScreenId.ROULETTE, timeout=1.0, interval=0.2):
                log.info("Ruleta cerrada; sigo el combate")
                return
        log.warning("La ruleta no se cerró tras varios taps; continúo igual")

    def _handle_devil_deal(self) -> None:
        # Por defecto rechazamos: el trato cuesta Max HP (riesgo de muerte).
        # Configurable con skills.json -> "devil_deal": "sign".
        action = str(self.picker.config.get("devil_deal", "reject")).lower()
        key = "devil_sign" if action == "sign" else "devil_reject"
        log.info("Trato del diablo detectado -> %s", key)
        self.ctx.tap_point("battle", key, money_check=False, settle=0.0)
        self.ctx.wait_until_not(ScreenId.DEVIL_DEAL, timeout=1.5, interval=0.2)

    def _pick_skill(self, screen) -> None:
        try:
            fallback = self.ctx.coords.regions("skill_select", "cards")
        except (KeyError, ValueError):
            fallback = None
        chosen = self.picker.choose(screen, fallback_regions=fallback)
        log.info(
            "Eligiendo carta %d (%s score=%d) -> (%d,%d)",
            chosen.index,
            chosen.skill_id,
            chosen.score,
            chosen.tap_x,
            chosen.tap_y,
        )
        self.ctx.tap(chosen.tap_x, chosen.tap_y, money_check=False, settle=0.0)
        self.ctx.wait_until_not(ScreenId.SKILL_SELECT, timeout=1.5, interval=0.2)

    def _grab_roulette(self) -> None:
        """Inicio del nivel 50: la ruleta aparece arriba. Movemos al personaje
        hacia arriba (swipe sostenido) para agarrarla y luego no nos movemos más."""
        c = self.ctx.coords
        try:
            a = c.point("battle", "grab_up_from")
            b = c.point("battle", "grab_up_to")
            ax, ay, bx, by = a.x, a.y, b.x, b.y
        except ValueError:
            ax, ay, bx, by = 450, 1250, 450, 520
        log.info("Agarrando ruleta inicial: movimiento hacia arriba")
        self.ctx.swipe(ax, ay, bx, by, duration_ms=450, settle=0.15)

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
        """Cierra resultado/recompensas post-run y confirma lobby."""
        from ..run_end_dismiss import dismiss_to_lobby, is_challenge_ended_screen

        if dismiss_to_lobby(self.ctx, max_rounds=4):
            log.info("Regreso al lobby confirmado")
            return True

        screen = self.ctx.device.screenshot()
        if is_challenge_ended_screen(screen):
            log.warning("Dismiss falló con post-run visible; reintento tap default")
            saved_tap = self.ctx.post_run_tap
            self.ctx.post_run_tap = None
            if dismiss_to_lobby(self.ctx, max_rounds=3):
                log.info("Regreso al lobby confirmado (tap alternativo)")
                self.ctx.post_run_tap = saved_tap
                return True
            self.ctx.post_run_tap = saved_tap
            log.warning("No se pudo cerrar post-run; fuerzo return_to_lobby")
            self.ctx.return_to_lobby()
            return is_lobby(self.ctx.device.screenshot())

        if self.ctx.current_screen() in _IN_COMBAT_SCREENS:
            log.warning("Dismiss abortado: partida aún en curso (falso fin?)")
            return False
        log.warning("No se confirmó regreso al lobby tras la partida")
        self.ctx.return_to_lobby()
        return is_lobby(self.ctx.device.screenshot())

    def _collect_event_run_end(self, timeout: float = 90.0) -> None:
        """Cierra victoria/derrota y recompensas sin exigir lobby (Events/Dungeon)."""
        from ..combat_prompts import dismiss_shackled_challenge_end, is_shackled_challenge_end

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
            if is_shackled_challenge_end(screen):
                log.info("Fin de run evento (challenge ended) -> tap empty")
                dismiss_shackled_challenge_end(self.ctx)
                stable_out = 0
                sleep(0.6)
                continue
            sid = self.ctx.current_screen()
            if sid in (ScreenId.VICTORY, ScreenId.DEFEAT):
                log.info("Fin de run evento (%s) -> continue", sid.value)
                self.ctx.tap_point("run_end", "continue", money_check=True, settle=0.0)
                self.ctx.wait_until_not({ScreenId.VICTORY, ScreenId.DEFEAT}, timeout=2.5, interval=0.25)
                stable_out = 0
                continue
            if sid in combat:
                stable_out = 0
                sleep(0.4)
                continue
            stable_out += 1
            if stable_out >= 2:
                log.info("Run de evento finalizado (pantalla=%s)", sid.value)
                return
            try:
                self.ctx.tap_point("events", "dismiss_rewards", money_check=False, settle=0.3)
            except ValueError:
                pass
            sleep(0.5)
        log.warning("Timeout cerrando run de evento")
