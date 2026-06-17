from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "screens"


def fixture_path(*parts: str) -> Path:
    return FIXTURES_DIR.joinpath(*parts)


def load_fixture(*parts: str) -> np.ndarray:
    path = fixture_path(*parts)
    if path.suffix.lower() != ".png":
        path = path.with_suffix(".png")
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(path)
    return img


def save_fixture(img: np.ndarray, *parts: str) -> Path:
    path = fixture_path(*parts)
    if path.suffix.lower() != ".png":
        path = path.with_suffix(".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path


def list_fixtures() -> list[str]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(
        str(p.relative_to(FIXTURES_DIR)).replace("\\", "/")
        for p in FIXTURES_DIR.rglob("*.png")
    )
