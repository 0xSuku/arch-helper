"""Catálogo de íconos de skill (todas las cartas vistas, deduplicadas por hash)."""
from __future__ import annotations

import json
from typing import Any

import cv2
import numpy as np

from .device import ROOT
from .log import get_logger
from .vision import TEMPLATES

log = get_logger("skill_catalog")

CATALOG_DIR = TEMPLATES / "skills_catalog"
MANIFEST_PATH = ROOT / "config" / "skills-catalog.json"


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"entries": {}}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _save_manifest(data: dict[str, Any]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fingerprint(card: np.ndarray) -> str:
    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = resized[:, 1:] > resized[:, :-1]
    bits = "".join("1" if b else "0" for b in diff.flatten())
    return f"{int(bits, 2):016x}"


def register_card(
    card: np.ndarray,
    *,
    skill_id: str,
    category: str,
    confidence: float,
) -> tuple[str, bool]:
    """Registra una carta en el catálogo. Devuelve (catalog_id, is_new)."""
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    fp = fingerprint(card)
    manifest = _load_manifest()
    entries: dict[str, Any] = manifest.setdefault("entries", {})
    path = CATALOG_DIR / f"{fp}.png"
    is_new = not path.exists()
    if is_new:
        cv2.imwrite(str(path), card)

    catalog_id = skill_id if skill_id != "unknown" else f"catalog/{fp}"
    prev = entries.get(fp, {})
    best_conf = float(prev.get("confidence", 0.0))
    if is_new or confidence >= best_conf:
        entries[fp] = {
            "file": path.name,
            "skill_id": catalog_id,
            "category": category,
            "confidence": round(confidence, 3),
            "source": "matched" if skill_id != "unknown" else "unlabeled",
        }
        _save_manifest(manifest)
        if is_new:
            log.info("Catálogo + skill nuevo: %s (%s conf=%.2f)", catalog_id, category, confidence)
    return catalog_id, is_new


def list_catalog_entries() -> list[tuple[str, str, str, float]]:
    return [(r[1], r[2], r[3], r[4]) for r in list_catalog_entries_full()]


def list_catalog_entries_full() -> list[tuple[str, str, str, str, float]]:
    manifest = _load_manifest()
    rows: list[tuple[str, str, str, str, float]] = []
    for fp, meta in manifest.get("entries", {}).items():
        rows.append((
            fp,
            str(meta.get("skill_id", f"catalog/{fp}")),
            str(meta.get("category", "unknown")),
            str(meta.get("source", "catalog")),
            float(meta.get("confidence", 0.0)),
        ))
    return rows


def find_catalog_fp(skill_id: str) -> str | None:
    manifest = _load_manifest()
    for fp, meta in manifest.get("entries", {}).items():
        if str(meta.get("skill_id")) == skill_id:
            return fp
    if skill_id.startswith("catalog/"):
        fp = skill_id.removeprefix("catalog/")
        if fp in manifest.get("entries", {}):
            return fp
    return None


def update_catalog_entry(
    fp: str,
    *,
    skill_id: str,
    category: str,
) -> None:
    manifest = _load_manifest()
    entries: dict[str, Any] = manifest.setdefault("entries", {})
    if fp not in entries:
        raise ValueError(f"Entrada de catálogo no encontrada: {fp}")
    meta = dict(entries[fp])
    meta["skill_id"] = skill_id
    meta["category"] = category
    if skill_id.startswith("catalog/"):
        meta["source"] = meta.get("source", "unlabeled")
    else:
        meta["source"] = "labeled"
    entries[fp] = meta
    _save_manifest(manifest)
    log.info("Catálogo actualizado: %s -> %s [%s]", fp, skill_id, category)
