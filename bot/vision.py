"""Motor de visión: template matching multiescala, espera de elementos,
detección de cambios de pantalla y utilidades de recorte.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .device import Device, ROOT

TEMPLATES = ROOT / "templates"
DEFAULT_SCALES = (0.5, 0.65, 0.8, 1.0, 1.2, 1.5, 1.85, 2.25, 2.75)
# Íconos de skill: tamaño fijo, pocas escalas alcanzan.
SKILL_SCALES = (0.85, 1.0, 1.15)
DEFAULT_THRESHOLD = 0.80


@dataclass(frozen=True)
class Match:
    confidence: float
    cx: int
    cy: int
    w: int
    h: int

    @property
    def x(self) -> int:
        return self.cx - self.w // 2

    @property
    def y(self) -> int:
        return self.cy - self.h // 2


Region = tuple[int, int, int, int]  # (x, y, w, h) en espacio de captura


def _load_template(template: Path | str) -> np.ndarray:
    path = template if isinstance(template, Path) else TEMPLATES / template
    if not path.exists():
        raise FileNotFoundError(f"Template no encontrado: {path}")
    tpl = cv2.imread(str(path))
    if tpl is None:
        raise FileNotFoundError(f"Template ilegible: {path}")
    return tpl


def crop(screen: np.ndarray, region: Region) -> np.ndarray:
    x, y, w, h = region
    return screen[max(0, y) : y + h, max(0, x) : x + w]


def find_template(
    screen: np.ndarray,
    template: Path | str | np.ndarray,
    scales: tuple[float, ...] = DEFAULT_SCALES,
    region: Region | None = None,
) -> Match:
    """Mejor match multiescala. Si se da `region`, busca solo dentro de ella
    y traduce las coordenadas al espacio completo de la captura."""
    tpl = template if isinstance(template, np.ndarray) else _load_template(template)
    haystack = crop(screen, region) if region else screen
    off_x, off_y = (region[0], region[1]) if region else (0, 0)

    sh, sw = haystack.shape[:2]
    th0, tw0 = tpl.shape[:2]
    best: Match | None = None

    for scale in scales:
        th, tw = int(th0 * scale), int(tw0 * scale)
        if th < 8 or tw < 8 or th > sh or tw > sw:
            continue
        resized = cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(haystack, resized, cv2.TM_CCOEFF_NORMED)
        _, val, _, loc = cv2.minMaxLoc(res)
        cand = Match(float(val), off_x + loc[0] + tw // 2, off_y + loc[1] + th // 2, tw, th)
        if best is None or cand.confidence > best.confidence:
            best = cand

    if best is None:
        return Match(0.0, 0, 0, 0, 0)
    return best


def find_all(
    screen: np.ndarray,
    template: Path | str,
    threshold: float = DEFAULT_THRESHOLD,
    scale: float = 1.0,
    min_distance: int = 20,
) -> list[Match]:
    tpl = _load_template(template)
    th0, tw0 = tpl.shape[:2]
    tw, th = int(tw0 * scale), int(th0 * scale)
    resized = cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA) if scale != 1.0 else tpl
    res = cv2.matchTemplate(screen, resized, cv2.TM_CCOEFF_NORMED)

    matches: list[Match] = []
    ys, xs = np.where(res >= threshold)
    for x, y in sorted(zip(xs.tolist(), ys.tolist()), key=lambda p: -res[p[1], p[0]]):
        cx, cy = x + tw // 2, y + th // 2
        if any(abs(cx - m.cx) < min_distance and abs(cy - m.cy) < min_distance for m in matches):
            continue
        matches.append(Match(float(res[y, x]), cx, cy, tw, th))
    return matches


def matches(screen: np.ndarray, template: Path | str, threshold: float = DEFAULT_THRESHOLD, region: Region | None = None) -> bool:
    return find_template(screen, template, region=region).confidence >= threshold


def wait_for(
    device: Device,
    template: Path | str,
    timeout: float = 10.0,
    interval: float = 0.5,
    threshold: float = DEFAULT_THRESHOLD,
    region: Region | None = None,
) -> Match | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        screen = device.screenshot()
        match = find_template(screen, template, region=region)
        if match.confidence >= threshold:
            return match
        time.sleep(interval)
    return None


def find_card_icons(
    screen: np.ndarray,
    band: tuple[int, int] = (560, 840),
    white_thresh: int = 205,
    min_side: int = 90,
    max_side: int = 230,
) -> list[Region]:
    """Detecta los recuadros (casi blancos) de íconos de las cartas de skill.

    Funciona con 2 o 3 cartas. Devuelve regiones (x,y,w,h) ordenadas por x,
    recortadas al recuadro interno del ícono.
    """
    y0, y1 = band
    strip = screen[y0:y1, :]
    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    mask = (gray >= white_thresh).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))

    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes: list[Region] = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        if not (min_side <= w <= max_side and min_side <= h <= max_side):
            continue
        if area < (min_side * min_side) * 0.4:
            continue
        boxes.append((x, y0 + y, w, h))
    boxes.sort(key=lambda b: b[0])
    return boxes


def difference(a: np.ndarray, b: np.ndarray) -> float:
    """Diferencia media normalizada (0=idéntico, 1=opuesto) entre dos capturas."""
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    return float(np.mean(cv2.absdiff(a, b))) / 255.0


def screen_changed(a: np.ndarray, b: np.ndarray, threshold: float = 0.01) -> bool:
    return difference(a, b) >= threshold


DIGITS_DIR = TEMPLATES / "digits"
LEVEL50_ANCHOR = TEMPLATES / "anchors" / "level50.png"
DEFAULT_CAMPAIGN_FLOOR_BADGE: Region = (72, 562, 86, 74)


def _split_digit_columns(bw: np.ndarray) -> list[np.ndarray]:
    col = bw.sum(axis=0).astype(float)
    if col.size == 0 or col.max() <= 0:
        return []
    active = col >= col.max() * 0.22
    segments: list[np.ndarray] = []
    start: int | None = None
    for i, on in enumerate(active):
        if on and start is None:
            start = i
        elif not on and start is not None:
            segments.append(bw[:, start:i])
            start = None
    if start is not None:
        segments.append(bw[:, start:])
    return [s for s in segments if s.size > 0 and s.shape[1] >= 2]


def _load_digit_templates() -> dict[str, np.ndarray]:
    templates: dict[str, np.ndarray] = {}
    if DIGITS_DIR.exists():
        for path in sorted(DIGITS_DIR.glob("*.png")):
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                templates[path.stem] = img
    if templates or not LEVEL50_ANCHOR.exists():
        return templates

    anchor = cv2.imread(str(LEVEL50_ANCHOR), cv2.IMREAD_GRAYSCALE)
    if anchor is None:
        return templates
    badge = anchor[:, :52]
    _, badge_bw = cv2.threshold(badge, 150, 255, cv2.THRESH_BINARY)
    cols = _split_digit_columns(badge_bw)
    if len(cols) >= 2:
        templates.setdefault("5", cols[0])
        templates.setdefault("0", cols[1])
    return templates


def _match_digit(patch: np.ndarray, templates: dict[str, np.ndarray]) -> tuple[str, float]:
    if patch.size == 0 or not templates:
        return "", 0.0
    best_digit, best_conf = "", 0.0
    for digit, tpl in templates.items():
        th, tw = tpl.shape[:2]
        ph, pw = patch.shape[:2]
        if ph < 4 or pw < 2:
            continue
        resized = cv2.resize(patch, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(resized, tpl, cv2.TM_CCOEFF_NORMED)
        conf = float(res[0, 0]) if res.size else 0.0
        if conf > best_conf:
            best_digit, best_conf = digit, conf
    return best_digit, best_conf


def read_campaign_floor_badge(
    screen: np.ndarray,
    region: Region = DEFAULT_CAMPAIGN_FLOOR_BADGE,
    *,
    min_digit_conf: float = 0.45,
) -> int | None:
    """Lee el número del badge del piso seleccionado en el mapa de campaña."""
    patch = crop(screen, region)
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 155, 255, cv2.THRESH_BINARY)
    templates = _load_digit_templates()
    if not templates:
        return None

    digits: list[str] = []
    for col in _split_digit_columns(bw):
        digit, conf = _match_digit(col, templates)
        if conf >= min_digit_conf and digit:
            digits.append(digit)
    if not digits:
        return None
    try:
        value = int("".join(digits))
    except ValueError:
        return None
    return value if 1 <= value <= 99 else None
