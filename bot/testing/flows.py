"""Definición de flujos de combate para tests con screenshots o emulador."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..paths.base import BotContext
from ..paths.daily import DailyPath
from ..paths.play_level import PlayLevelPath
from ..screens import ScreenId, is_lobby


@dataclass(frozen=True)
class CombatFlowSpec:
    flow_id: str
    label: str
    claim: str | None = None
    needs_combat: bool = True
    needs_lobby_exit: bool = True


COMBAT_FLOWS: tuple[CombatFlowSpec, ...] = (
    CombatFlowSpec("farm", "Farm nivel 50 (energía)", claim=None),
    CombatFlowSpec("shackled_jungle", "Shackled Jungle", claim="shackled_jungle"),
    CombatFlowSpec("abyssal_tide", "Abyssal Tide", claim="abyssal_tide"),
    CombatFlowSpec("arena", "Arena", claim="arena"),
    CombatFlowSpec("peak_arena", "Peak Arena", claim="peak_arena"),
    CombatFlowSpec("rumble_ladder", "Rumble Ladder", claim="rumble_ladder"),
    CombatFlowSpec("seal_battle", "Seal Battle", claim="seal_battle"),
    CombatFlowSpec("monster_invasion", "Monster Invasion", claim="monster_invasion"),
    CombatFlowSpec("magic_plant_defense", "Magic Plant Defense", claim="magic_plant_defense"),
)


def flow_by_id(flow_id: str) -> CombatFlowSpec | None:
    for spec in COMBAT_FLOWS:
        if spec.flow_id == flow_id:
            return spec
    return None


@dataclass
class FlowRunResult:
    flow_id: str
    entered_combat: bool
    returned_lobby: bool
    taps: int
    backs: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.entered_combat and self.returned_lobby


class FlowProbeDevice:
    """Device que registra taps y simula transición lobby -> combate -> lobby."""

    def __init__(self, lobby_frame, battle_frame) -> None:
        from .mock_device import ScreenshotDevice

        self._inner = ScreenshotDevice([lobby_frame, battle_frame, lobby_frame])
        self.in_combat = False
        self.entered_combat = False

    def screenshot(self, save_as: str | None = None, *, retry_reconnect: bool = True):
        frame = self._inner.screenshot(save_as=save_as, retry_reconnect=retry_reconnect)
        if self.in_combat:
            self.entered_combat = True
        return frame

    def tap(self, x: float, y: float) -> None:
        self._inner.tap(x, y)
        if not self.in_combat and len(self._inner.taps) >= 2:
            self.in_combat = True
            self._inner.index = 1

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None:
        self._inner.swipe(x1, y1, x2, y2, duration_ms)

    def back(self) -> None:
        self._inner.back()
        if self.in_combat:
            self.in_combat = False
            self._inner.index = 2

    @property
    def taps(self) -> list[tuple[int, int]]:
        return self._inner.taps

    @property
    def backs(self) -> int:
        return self._inner.backs


def run_mock_flow(
    flow_id: str,
    *,
    lobby_factory: Callable[[], object],
    battle_factory: Callable[[], object],
) -> FlowRunResult:
    import numpy as np

    spec = flow_by_id(flow_id)
    if spec is None:
        return FlowRunResult(flow_id, False, False, 0, 0, error="flow desconocido")

    lobby = lobby_factory()
    battle = battle_factory()
    if lobby is None:
        lobby = np.zeros((1600, 900, 3), dtype=np.uint8)
        lobby[:, :] = (40, 120, 40)
    if battle is None:
        battle = np.zeros((1600, 900, 3), dtype=np.uint8)
        battle[:, :] = (70, 150, 70)

    device = FlowProbeDevice(lobby, battle)
    ctx = BotContext(device)

    try:
        if spec.claim:
            path = DailyPath(ctx, force=True)
            handler = path._claim_handler(spec.claim)
            handler()
        else:
            play = PlayLevelPath.__new__(PlayLevelPath)
            play.ctx = ctx
            play.survival_only = False
            play._enter_level = lambda: True
            play._wait_combat_start = lambda: True
            play._fight = lambda: "victory"
            play._collect_run_end = lambda: None
            play.run()
    except Exception as exc:  # noqa: BLE001
        return FlowRunResult(
            flow_id,
            device.entered_combat,
            is_lobby(device.screenshot()),
            len(device.taps),
            device.backs,
            error=str(exc),
        )

    screen = device.screenshot()
    return FlowRunResult(
        flow_id,
        device.entered_combat,
        is_lobby(screen) or ctx.current_screen() == ScreenId.LOBBY,
        len(device.taps),
        device.backs,
    )


def run_live_flow(flow_id: str, ctx: BotContext) -> FlowRunResult:
    spec = flow_by_id(flow_id)
    if spec is None:
        return FlowRunResult(flow_id, False, False, 0, 0, error="flow desconocido")
    before = ctx.current_screen()
    entered = before in {
        ScreenId.BATTLE,
        ScreenId.SKILL_SELECT,
        ScreenId.ROULETTE,
        ScreenId.DEVIL_DEAL,
    }
    try:
        if spec.claim:
            DailyPath(ctx, force=True).run_one(spec.claim)
        else:
            from ..navigation import prepare_for_task

            prepare_for_task(ctx, "farm")
            PlayLevelPath(ctx, level=50, games=1, battle_timeout=120.0).run()
    except Exception as exc:  # noqa: BLE001
        return FlowRunResult(flow_id, entered, is_lobby(ctx.device.screenshot()), 0, 0, error=str(exc))

    after_combat = ctx.current_screen() in {
        ScreenId.BATTLE,
        ScreenId.SKILL_SELECT,
        ScreenId.ROULETTE,
        ScreenId.DEVIL_DEAL,
    }
    return FlowRunResult(
        flow_id,
        entered or after_combat,
        is_lobby(ctx.device.screenshot()),
        0,
        0,
    )
