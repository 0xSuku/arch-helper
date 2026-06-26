"""User data paths (presets, run state).

In portable mode, everything lives in ``data/`` next to the project (or ``ARCHERO_DATA_DIR``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .device import ROOT
from .settings import load_env

_DATA_DIR: Path | None = None


def data_dir() -> Path:
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR
    env = load_env().get("ARCHERO_DATA_DIR")
    if env:
        path = Path(env)
    else:
        path = ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    _DATA_DIR = path
    return path


def presets_file() -> Path:
    return data_dir() / "presets.json"


def run_state_file() -> Path:
    return data_dir() / "run-state.json"


def bundled_presets_file() -> Path:
    return ROOT / "config" / "presets.json"


def seed_user_presets() -> Path:
    """Copy bundled presets to data/ if the user does not have a file yet."""
    target = presets_file()
    if target.exists():
        return target
    bundled = bundled_presets_file()
    if bundled.exists():
        target.write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        target.write_text(json.dumps({"presets": []}, indent=2), encoding="utf-8")
    return target


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
