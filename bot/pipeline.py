"""Pipeline executor: chains actions with persistent state and recovery."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .actions import describe_step, execute_step, normalize_steps
from .data_paths import run_state_file, write_json
from .failsafes import StopRequested
from .log import get_logger
from .paths.base import BotContext
from .presets import Preset

log = get_logger("pipeline")

STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_DONE = "done"
STEP_FAILED = "failed"
STEP_SKIPPED = "skipped"


@dataclass
class StepState:
    step: dict[str, Any]
    status: str = STEP_PENDING
    error: str | None = None
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "error": self.error,
            "attempts": self.attempts,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StepState":
        return cls(
            step=dict(raw["step"]),
            status=str(raw.get("status", STEP_PENDING)),
            error=raw.get("error"),
            attempts=int(raw.get("attempts", 0)),
        )


@dataclass
class PipelineState:
    preset_id: str | None
    preset_name: str
    recover_on_failure: bool
    current_index: int
    steps: list[StepState] = field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "preset_name": self.preset_name,
            "recover_on_failure": self.recover_on_failure,
            "current_index": self.current_index,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PipelineState":
        return cls(
            preset_id=raw.get("preset_id"),
            preset_name=str(raw.get("preset_name", "")),
            recover_on_failure=bool(raw.get("recover_on_failure", True)),
            current_index=int(raw.get("current_index", 0)),
            steps=[StepState.from_dict(s) for s in raw.get("steps", [])],
            started_at=str(raw.get("started_at", "")),
            updated_at=str(raw.get("updated_at", "")),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_state() -> PipelineState | None:
    path = run_state_file()
    if not path.exists():
        return None
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not raw:
        return None
    return PipelineState.from_dict(raw)


def save_state(state: PipelineState) -> None:
    state.updated_at = _now_iso()
    write_json(run_state_file(), state.to_dict())


def clear_state() -> None:
    path = run_state_file()
    if path.exists():
        path.unlink()


def new_state(
    *,
    preset: Preset | None,
    steps: list[dict[str, Any]],
    recover_on_failure: bool,
    name: str,
) -> PipelineState:
    return PipelineState(
        preset_id=preset.id if preset else None,
        preset_name=name,
        recover_on_failure=recover_on_failure,
        current_index=0,
        steps=[StepState(step=s) for s in steps],
        started_at=_now_iso(),
        updated_at=_now_iso(),
    )


def recover_game(ctx: BotContext) -> bool:
    from .recovery import reboot_emulator_and_wait_lobby

    log.warning("Recovery: restarting emulator and reopening the game...")
    ok = reboot_emulator_and_wait_lobby(ctx.device)
    if ok:
        log.info("Recovery complete; lobby ready.")
    else:
        log.error("Recovery failed; check emulator and ADB.")
    return ok


class PipelineRunner:
    def __init__(self, ctx: BotContext) -> None:
        self.ctx = ctx

    def run(
        self,
        state: PipelineState,
        *,
        resume: bool = False,
        max_recovery_per_step: int = 1,
    ) -> None:
        if not resume:
            state.current_index = 0
            for step_state in state.steps:
                step_state.status = STEP_PENDING
                step_state.error = None
                step_state.attempts = 0

        save_state(state)
        log.info(
            "Pipeline %r: %d steps (recover=%s)",
            state.preset_name,
            len(state.steps),
            state.recover_on_failure,
        )

        while state.current_index < len(state.steps):
            step_state = state.steps[state.current_index]
            if step_state.status == STEP_DONE:
                state.current_index += 1
                continue

            label = describe_step(step_state.step)
            log.info(
                "Step %d/%d: %s",
                state.current_index + 1,
                len(state.steps),
                label,
            )
            step_state.status = STEP_RUNNING
            step_state.attempts += 1
            save_state(state)

            try:
                execute_step(self.ctx, step_state.step)
            except StopRequested:
                step_state.status = STEP_FAILED
                step_state.error = "Stopped by user"
                save_state(state)
                raise
            except Exception as exc:  # noqa: BLE001
                step_state.status = STEP_FAILED
                step_state.error = str(exc)
                save_state(state)
                log.error("Step failed (%s): %s", label, exc)

                if (
                    state.recover_on_failure
                    and step_state.attempts <= max_recovery_per_step
                ):
                    if recover_game(self.ctx):
                        log.info("Retrying step after recovery...")
                        step_state.status = STEP_PENDING
                        step_state.error = None
                        save_state(state)
                        continue

                raise RuntimeError(
                    f"Pipeline stopped at step {state.current_index + 1} ({label}): {exc}"
                ) from exc

            step_state.status = STEP_DONE
            step_state.error = None
            state.current_index += 1
            save_state(state)
            time.sleep(0.3)

        log.info("Pipeline completed: %s", state.preset_name)
        clear_state()


def build_state_from_preset(preset: Preset) -> PipelineState:
    return new_state(
        preset=preset,
        steps=preset.steps,
        recover_on_failure=preset.recover_on_failure,
        name=preset.name,
    )


def build_state_from_steps(
    steps: list[dict[str, Any] | str],
    *,
    name: str = "inline",
    recover_on_failure: bool = True,
) -> PipelineState:
    normalized = normalize_steps(steps)
    return new_state(
        preset=None,
        steps=normalized,
        recover_on_failure=recover_on_failure,
        name=name,
    )
