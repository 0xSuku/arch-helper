"""Carga de configuración (coords y skills) desde config/*.json."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .device import ROOT

CONFIG_DIR = ROOT / "config"
COORDS_FILE = CONFIG_DIR / "coords.json"
SKILLS_FILE = CONFIG_DIR / "skills.json"


@dataclass(frozen=True)
class Point:
    x: int
    y: int
    label: str = ""


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Falta archivo de configuración: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


class Coords:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def load(cls) -> "Coords":
        return cls(_load(COORDS_FILE))

    def raw(self, section: str, key: str) -> dict[str, Any]:
        try:
            return self._data[section][key]
        except KeyError as exc:
            raise KeyError(f"Coordenada no definida: {section}.{key}") from exc

    def point(self, section: str, key: str) -> Point:
        raw = self.raw(section, key)
        x, y = int(raw.get("x", 0)), int(raw.get("y", 0))
        if x <= 0 or y <= 0:
            raise ValueError(
                f"Punto sin calibrar: {section}.{key} (= {x},{y}). "
                f"Ejecutá 'python -m bot.cli calibrate' para registrarlo."
            )
        return Point(x, y, str(raw.get("label", "")))

    def region(self, section: str, key: str) -> tuple[int, int, int, int]:
        raw = self.raw(section, key)
        return int(raw["x"]), int(raw["y"]), int(raw["w"]), int(raw["h"])

    def regions(self, section: str, key: str) -> list[tuple[int, int, int, int]]:
        items = self._data[section][key]
        return [(int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"])) for r in items]

    def list_points(self, section: str, key: str) -> list[Point]:
        items = self._data[section][key]
        return [Point(int(p["x"]), int(p["y"]), str(p.get("label", ""))) for p in items]


def load_skills() -> dict[str, Any]:
    return _load(SKILLS_FILE)


def save_skills(data: dict[str, Any]) -> None:
    SKILLS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
