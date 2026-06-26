"""Presets: saved action sequences."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .actions import describe_step, normalize_steps
from .data_paths import presets_file, read_json, seed_user_presets, write_json

_PRESET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    description: str
    steps: list[dict[str, Any]]
    recover_on_failure: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "recover_on_failure": self.recover_on_failure,
            "steps": self.steps,
        }


def _load_store() -> dict[str, Any]:
    seed_user_presets()
    return read_json(presets_file())


def _save_store(data: dict[str, Any]) -> None:
    write_json(presets_file(), data)


def list_presets() -> list[Preset]:
    data = _load_store()
    out: list[Preset] = []
    for raw in data.get("presets", []):
        try:
            out.append(_preset_from_raw(raw))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def get_preset(preset_id: str) -> Preset | None:
    key = preset_id.strip().lower()
    for preset in list_presets():
        if preset.id == key:
            return preset
    return None


def _preset_from_raw(raw: dict[str, Any]) -> Preset:
    preset_id = str(raw["id"]).strip().lower()
    if not _PRESET_ID_RE.match(preset_id):
        raise ValueError(f"Invalid preset ID: {preset_id!r}")
    steps = normalize_steps(raw.get("steps", []))
    if not steps:
        raise ValueError(f"Preset {preset_id!r} has no steps")
    return Preset(
        id=preset_id,
        name=str(raw.get("name", preset_id)),
        description=str(raw.get("description", "")),
        steps=steps,
        recover_on_failure=bool(raw.get("recover_on_failure", True)),
    )


def save_preset(
    preset_id: str,
    *,
    name: str,
    description: str = "",
    steps: list[dict[str, Any] | str],
    recover_on_failure: bool = True,
    overwrite: bool = False,
) -> Preset:
    key = preset_id.strip().lower()
    if not _PRESET_ID_RE.match(key):
        raise ValueError(
            f"Invalid ID {key!r}. Use lowercase letters, numbers, hyphen, or underscore."
        )
    preset = Preset(
        id=key,
        name=name.strip() or key,
        description=description.strip(),
        steps=normalize_steps(steps),
        recover_on_failure=recover_on_failure,
    )
    data = _load_store()
    presets: list[dict[str, Any]] = list(data.get("presets", []))
    for i, existing in enumerate(presets):
        if str(existing.get("id", "")).lower() == key:
            if not overwrite:
                raise ValueError(f"Preset {key!r} already exists. Use --overwrite to replace it.")
            presets[i] = preset.to_dict()
            break
    else:
        presets.append(preset.to_dict())
    data["presets"] = presets
    _save_store(data)
    return preset


def delete_preset(preset_id: str) -> bool:
    key = preset_id.strip().lower()
    data = _load_store()
    presets = list(data.get("presets", []))
    kept = [p for p in presets if str(p.get("id", "")).lower() != key]
    if len(kept) == len(presets):
        return False
    data["presets"] = kept
    _save_store(data)
    return True


def format_preset_table() -> str:
    lines = ["ID                  Name                           Steps"]
    lines.append("-" * 72)
    for preset in list_presets():
        step_labels = " -> ".join(describe_step(s) for s in preset.steps)
        if len(step_labels) > 36:
            step_labels = step_labels[:33] + "..."
        lines.append(f"{preset.id:<20}{preset.name[:30]:<30}{step_labels}")
    return "\n".join(lines)
