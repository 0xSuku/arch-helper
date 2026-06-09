"""Combate reutilizable (Events, Arena, Dungeon, etc.)."""
from __future__ import annotations

from .paths.base import BotContext
from .paths.play_level import PlayLevelPath


class CombatRunner:
    def __init__(
        self,
        ctx: BotContext,
        *,
        battle_timeout: float = 180.0,
        dodge: bool = False,
        skills_only: bool = False,
        afk_only: bool = False,
    ) -> None:
        self._path = PlayLevelPath(
            ctx,
            games=1,
            battle_timeout=battle_timeout,
            dodge=dodge,
            skills_only=skills_only,
            afk_only=afk_only,
        )

    def run_until_end(self) -> str:
        return self._path._fight()

    def collect_end(self) -> None:
        self._path._collect_run_end()

    def collect_event_end(self) -> bool:
        return self._path._collect_event_run_end()
