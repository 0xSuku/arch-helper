"""Manifest de claims diarios: checks verificados, reset a las 21:00, badges rojos."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .device import ROOT
from .log import get_logger

log = get_logger("daily_checks")

MANIFEST_PATH = ROOT / "config" / "daily-claims.json"


def has_red_badge(
    screen: np.ndarray,
    cx: int,
    cy: int,
    *,
    radius: int = 20,
    offset_x: int = 16,
    offset_y: int = -16,
    min_pixels: int = 55,
) -> bool:
    """Detect red notification dot near an icon (top-right corner)."""
    bx = cx + offset_x
    by = cy + offset_y
    x0 = max(0, bx - radius)
    y0 = max(0, by - radius)
    x1 = min(screen.shape[1], bx + radius)
    y1 = min(screen.shape[0], by + radius)
    if x1 <= x0 or y1 <= y0:
        return False
    roi = screen[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    low1 = cv2.inRange(hsv, (0, 110, 110), (12, 255, 255))
    low2 = cv2.inRange(hsv, (165, 110, 110), (180, 255, 255))
    return cv2.countNonZero(low1 | low2) >= min_pixels


class DailyChecks:
    def __init__(self, *, force: bool = False) -> None:
        self.force = force
        self._data = self._load()
        self._maybe_reset_period()

    @staticmethod
    def _load() -> dict[str, Any]:
        if not MANIFEST_PATH.exists():
            return {"reset_hour_local": 21, "claims": {}}
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def save(self) -> None:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(self._data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def reset_hour(self) -> int:
        return int(self._data.get("reset_hour_local", 21))

    def _period_start(self) -> datetime:
        now = datetime.now()
        reset = now.replace(hour=self.reset_hour(), minute=0, second=0, microsecond=0)
        if now < reset:
            reset -= timedelta(days=1)
        return reset

    def _maybe_reset_period(self) -> None:
        period_start = self._period_start().isoformat(timespec="seconds")
        if self._data.get("period_start") == period_start:
            return
        log.info("Nuevo periodo diario (reset %02d:00); limpio checks verificados", self.reset_hour())
        self._data["period_start"] = period_start
        for claim in self._data.get("claims", {}).values():
            if isinstance(claim, dict):
                claim["verified"] = False
        self.save()

    def is_verified(self, claim_id: str) -> bool:
        claim = self._data.get("claims", {}).get(claim_id)
        if not isinstance(claim, dict):
            return False
        return bool(claim.get("verified"))

    def mark_verified(self, claim_id: str) -> None:
        claims = self._data.setdefault("claims", {})
        entry = claims.setdefault(claim_id, {})
        entry["verified"] = True
        entry["verified_at"] = datetime.now().isoformat(timespec="seconds")
        self.save()
        log.info("Check ✓ %s", claim_id)

    def unmark(self, claim_id: str | None) -> None:
        if claim_id is None or claim_id == "all":
            for claim in self._data.get("claims", {}).values():
                if isinstance(claim, dict):
                    claim["verified"] = False
            self.save()
            log.info("Checks reseteados (todos)")
            return
        claim = self._data.get("claims", {}).get(claim_id)
        if isinstance(claim, dict):
            claim["verified"] = False
            self.save()
            log.info("Check reseteado: %s", claim_id)

    def should_run(self, claim_id: str) -> bool:
        if self.force:
            return True
        if self.is_verified(claim_id):
            log.info("Skip %s (verificado hoy)", claim_id)
            return False
        return True

    def status_lines(self) -> list[str]:
        lines: list[str] = []
        period = self._data.get("period_start", "?")
        lines.append(f"Periodo desde: {period} (reset {self.reset_hour():02d}:00)")
        for claim_id, meta in sorted(self._data.get("claims", {}).items()):
            if not isinstance(meta, dict):
                continue
            flag = "✓" if meta.get("verified") else " "
            name = meta.get("name", claim_id)
            lines.append(f"  [{flag}] {claim_id}: {name}")
        return lines
