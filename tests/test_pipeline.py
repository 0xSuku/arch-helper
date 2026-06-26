"""Tests del sistema de pipeline y presets."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.actions import describe_step, normalize_step, normalize_steps, parse_inline_step
from bot.data_paths import presets_file, run_state_file, seed_user_presets
from bot.pipeline import (
    PipelineState,
    StepState,
    build_state_from_steps,
    clear_state,
    load_state,
    save_state,
)
from bot.presets import get_preset, list_presets, save_preset


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ARCHERO_DATA_DIR", str(data))
    import bot.data_paths as dp

    dp._DATA_DIR = None
    bundled = Path(__file__).resolve().parents[1] / "config" / "presets.json"
    (data / "presets.json").write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")
    return data


def test_parse_inline_arena_farm() -> None:
    step = parse_inline_step("arena:5")
    assert step["action"] == "claim"
    assert step["name"] == "arena"
    assert step["fights"] == 5

    farm = parse_inline_step("farm:forever")
    assert farm["action"] == "farm"
    assert farm["forever"] is True


def test_normalize_steps_chain() -> None:
    steps = normalize_steps(["arena:5", {"action": "shackled", "runs": 2}, "farm:forever"])
    assert len(steps) == 3
    assert steps[0]["name"] == "arena"
    assert steps[1]["name"] == "shackled_jungle"
    assert steps[1]["runs"] == 2
    assert steps[2]["forever"] is True


def test_describe_step() -> None:
    assert "arena" in describe_step({"action": "claim", "name": "arena", "fights": 5})
    assert describe_step({"action": "farm", "forever": True}) == "farm forever"


def test_seed_and_list_presets(isolated_data: Path) -> None:
    seed_user_presets()
    presets = list_presets()
    ids = {p.id for p in presets}
    assert "5-arena-farm" in ids
    preset = get_preset("5-arena-farm")
    assert preset is not None
    assert len(preset.steps) == 2
    assert preset.steps[0]["fights"] == 5


def test_save_preset(isolated_data: Path) -> None:
    seed_user_presets()
    preset = save_preset(
        "mi-bot",
        name="Mi bot",
        steps=["arena:3", "farm:forever"],
        overwrite=True,
    )
    assert preset.id == "mi-bot"
    assert get_preset("mi-bot") is not None
    raw = json.loads(presets_file().read_text(encoding="utf-8"))
    assert any(p["id"] == "mi-bot" for p in raw["presets"])


def test_pipeline_state_persistence(isolated_data: Path) -> None:
    clear_state()
    state = build_state_from_steps(["arena:2"], name="test")
    state.steps[0].status = "failed"
    state.steps[0].error = "timeout"
    state.current_index = 0
    save_state(state)

    loaded = load_state()
    assert loaded is not None
    assert loaded.preset_name == "test"
    assert loaded.steps[0].status == "failed"
    assert loaded.steps[0].error == "timeout"
    clear_state()
    assert load_state() is None


def test_pipeline_state_roundtrip() -> None:
    state = PipelineState(
        preset_id="x",
        preset_name="X",
        recover_on_failure=True,
        current_index=1,
        steps=[StepState(step={"action": "farm", "forever": True}, status="done")],
    )
    restored = PipelineState.from_dict(state.to_dict())
    assert restored.preset_id == "x"
    assert restored.steps[0].step["forever"] is True
