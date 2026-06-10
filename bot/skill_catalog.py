"""Catálogo de íconos de skill (todas las cartas vistas, deduplicadas por hash)."""
from __future__ import annotations

import json
from datetime import datetime
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
    context: str = "play",
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

    prev = entries.get(fp, {})
    prev_skill_id = str(prev.get("skill_id", ""))
    prev_is_labeled = bool(
        prev_skill_id
        and not prev_skill_id.startswith("catalog/")
        and prev_skill_id != "unknown"
    )
    catalog_id = prev_skill_id if prev_is_labeled and skill_id == "unknown" else skill_id
    if catalog_id == "unknown":
        catalog_id = f"catalog/{fp}"
    best_conf = float(prev.get("confidence", 0.0))
    now = datetime.now().isoformat(timespec="seconds")
    seen_count = int(prev.get("seen_count", 0)) + 1
    needs_label = not prev_is_labeled and (skill_id == "unknown" or catalog_id.startswith("catalog/"))
    if is_new or confidence >= best_conf:
        meta = {
            "file": path.name,
            "skill_id": catalog_id,
            "category": category,
            "confidence": round(confidence, 3),
            "source": "matched" if skill_id != "unknown" else "unlabeled",
            "needs_label": needs_label,
        }
    else:
        meta = dict(prev)
    meta.setdefault("first_seen_at", prev.get("first_seen_at") or now)
    meta["last_seen_at"] = now
    meta["seen_count"] = seen_count
    meta["last_confidence"] = round(confidence, 3)
    meta["best_confidence"] = max(
        float(meta.get("best_confidence", 0.0)),
        round(confidence, 3),
        best_conf,
    )
    meta["source_context"] = context
    if needs_label:
        meta["needs_label"] = True
    entries[fp] = meta
    _save_manifest(manifest)
    if is_new:
        log.info("Catálogo + skill nuevo: %s (%s conf=%.2f)", catalog_id, category, confidence)
    return catalog_id, is_new


def list_pending_entries() -> list[dict[str, Any]]:
    manifest = _load_manifest()
    rows: list[dict[str, Any]] = []
    for fp, meta in manifest.get("entries", {}).items():
        if not bool(meta.get("needs_label", str(meta.get("skill_id", "")).startswith("catalog/"))):
            continue
        rows.append({
            "fp": fp,
            "id": str(meta.get("skill_id", f"catalog/{fp}")),
            "file": str(meta.get("file", f"{fp}.png")),
            "category": str(meta.get("category", "unknown")),
            "source": str(meta.get("source", "unlabeled")),
            "confidence": float(meta.get("confidence", 0.0)),
            "last_confidence": float(meta.get("last_confidence", meta.get("confidence", 0.0))),
            "best_confidence": float(meta.get("best_confidence", meta.get("confidence", 0.0))),
            "seen_count": int(meta.get("seen_count", 1)),
            "first_seen_at": str(meta.get("first_seen_at", "")),
            "last_seen_at": str(meta.get("last_seen_at", "")),
            "source_context": str(meta.get("source_context", "")),
        })
    rows.sort(key=lambda r: (-int(r["seen_count"]), str(r["last_seen_at"]), str(r["fp"])))
    return rows


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
        meta["needs_label"] = True
    else:
        meta["source"] = "labeled"
        meta["needs_label"] = False
    entries[fp] = meta
    _save_manifest(manifest)
    log.info("Catálogo actualizado: %s -> %s [%s]", fp, skill_id, category)
