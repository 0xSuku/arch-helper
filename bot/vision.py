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
HUNT_CHANCES_DIR = TEMPLATES / "hunt_chances"
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


def _load_hunt_chance_templates() -> dict[str, np.ndarray]:
    templates: dict[str, np.ndarray] = {}
    if not HUNT_CHANCES_DIR.exists():
        return templates
    for path in sorted(HUNT_CHANCES_DIR.glob("*.png")):
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            templates[path.stem] = img
    return templates


def read_hunt_chances(
    screen: np.ndarray,
    region: Region,
    *,
    min_conf: float = 0.55,
) -> int | None:
    """Lee el número al final de "Chances: N" en el popup Quick Hunt."""
    patch = crop(screen, region)
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    # Texto marrón oscuro sobre fondo beige.
    mask = cv2.inRange(hsv, (5, 60, 40), (35, 255, 170))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    boxes: list[tuple[int, int, int, int, int]] = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area >= 25 and h >= 10:
            boxes.append((x, y, w, h, area))
    if not boxes:
        return None

    x, y, w, h, _area = max(boxes, key=lambda b: b[0] + b[2])
    pad = 3
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(mask.shape[1], x + w + pad)
    y1 = min(mask.shape[0], y + h + pad)
    digit = mask[y0:y1, x0:x1]

    templates = _load_hunt_chance_templates()
    best_digit, best_conf = _match_digit(digit, templates)
    if not best_digit or best_conf < min_conf:
        return None
    try:
        return int(best_digit)
    except ValueError:
        return None


def _trim_glyph(tpl: np.ndarray) -> np.ndarray:
    ys, xs = np.where(tpl > 0)
    if ys.size == 0 or xs.size == 0:
        return tpl
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    return tpl[y0:y1, x0:x1]


def _arena_glyph_templates() -> dict[str, np.ndarray]:
    templates = _load_digit_templates()
    trimmed: dict[str, np.ndarray] = {}
    for k, v in templates.items():
        if k in "0123456789" or k in ("dot", "M"):
            trimmed[k] = _trim_glyph(v)
    return trimmed


ARENA_POWER_SLOTS: tuple[tuple[int, int, str], ...] = (
    (1, 16, "digit"),
    (28, 15, "digit"),
    (43, 12, "digit"),
    (55, 20, "M"),
)


def _match_arena_slot(
    bw: np.ndarray,
    x0: int,
    width: int,
    kind: str,
    templates: dict[str, np.ndarray],
) -> tuple[str, float]:
    h = bw.shape[0]
    x1 = min(bw.shape[1], x0 + width)
    if x0 >= x1:
        return "", 0.0
    sub = bw[:h, x0:x1]
    if sub.size == 0:
        return "", 0.0

    if kind == "dot":
        tpl = templates.get("dot")
        if tpl is None:
            return "", 0.0
        th, tw = tpl.shape[:2]
        resized = cv2.resize(sub, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(resized, tpl, cv2.TM_CCOEFF_NORMED)
        conf = float(res[0, 0]) if res.size else 0.0
        return (".", conf) if conf >= 0.35 else ("", conf)

    if kind == "M":
        tpl = templates.get("M")
        if tpl is None:
            return "", 0.0
        th, tw = tpl.shape[:2]
        resized = cv2.resize(sub, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(resized, tpl, cv2.TM_CCOEFF_NORMED)
        conf = float(res[0, 0]) if res.size else 0.0
        return ("M", conf) if conf >= 0.35 else ("", conf)

    best_ch, best_conf = "", 0.0
    for ch, tpl in templates.items():
        if ch in ("dot", "M"):
            continue
        if int(tpl.sum()) < 40:
            continue
        th, tw = tpl.shape[:2]
        resized = cv2.resize(sub, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(resized, tpl, cv2.TM_CCOEFF_NORMED)
        conf = float(res[0, 0]) if res.size else 0.0
        if conf > best_conf:
            best_ch, best_conf = ch, conf
    return (best_ch, best_conf) if best_conf >= 0.38 else ("", best_conf)


ARENA_POWER_ROW_SCAN = (190, 520, 90, 680)
ARENA_POWER_ROW_MIN_DARK = 380
ARENA_POWER_ROW_MIN_GAP = 120


def _cluster_arena_row_ys(candidates: list[int]) -> list[int]:
    if not candidates:
        return []
    clusters: list[list[int]] = [[candidates[0]]]
    for y in candidates[1:]:
        if y - clusters[-1][-1] <= 18:
            clusters[-1].append(y)
        else:
            clusters.append([y])
    merged = [int(sum(c) / len(c)) for c in clusters if len(c) >= 2]
    if len(merged) >= 2:
        return merged
    return [int(sum(c) / len(c)) for c in clusters]


ARENA_POPUP_TITLE_REGION: Region = (300, 300, 260, 80)
ARENA_ROW_OFFSETS: tuple[int, ...] = (225, 341, 533, 625, 733)


def arena_popup_title_y(screen: np.ndarray) -> int | None:
    try:
        match = find_template(
            screen,
            "anchors/arena_opponents_popup.png",
            region=ARENA_POPUP_TITLE_REGION,
        )
    except FileNotFoundError:
        return None
    if match.confidence < 0.72:
        return None
    return match.cy


def find_arena_power_row_ys(screen: np.ndarray) -> list[int]:
    title_y = arena_popup_title_y(screen)
    if title_y is not None:
        return [title_y + off for off in ARENA_ROW_OFFSETS]
    return _find_arena_power_row_ys_scan(screen)


def _find_arena_power_row_ys_scan(screen: np.ndarray) -> list[int]:
    x, y0, w, h = ARENA_POWER_ROW_SCAN
    hay = crop(screen, (x, y0, w, h))
    gray = cv2.cvtColor(hay, cv2.COLOR_BGR2GRAY)
    candidates: list[int] = []
    for row in range(0, gray.shape[0] - 22, 3):
        patch = gray[row : row + 22, :]
        if int((patch < 90).sum()) >= ARENA_POWER_ROW_MIN_DARK:
            candidates.append(y0 + row + 11)
    rows = _cluster_arena_row_ys(candidates)
    if len(rows) < 2:
        return rows
    gaps = [rows[i + 1] - rows[i] for i in range(len(rows) - 1)]
    median_gap = sorted(gaps)[len(gaps) // 2]
    if median_gap < ARENA_POWER_ROW_MIN_GAP:
        return rows
    filtered = [rows[0]]
    for y in rows[1:]:
        if y - filtered[-1] >= median_gap * 0.65:
            filtered.append(y)
    return filtered


ARENA_POWER_PATCH_X = 175
ARENA_POWER_PATCH_Y_OFF = -18
ARENA_POWER_PATCH_W = 95
ARENA_POWER_PATCH_H = 36
ARENA_DIGITS_DIR = TEMPLATES / "arena" / "digits"


def _load_arena_digit_templates() -> dict[str, np.ndarray]:
    templates: dict[str, np.ndarray] = {}
    if not ARENA_DIGITS_DIR.exists():
        return templates
    for path in sorted(ARENA_DIGITS_DIR.glob("*.png")):
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            templates[path.stem] = img
    return templates


def _arena_power_patch(screen: np.ndarray, row_y: int) -> np.ndarray:
    return crop(
        screen,
        (
            ARENA_POWER_PATCH_X,
            row_y + ARENA_POWER_PATCH_Y_OFF,
            ARENA_POWER_PATCH_W,
            ARENA_POWER_PATCH_H,
        ),
    )


def _arena_power_bw(patch: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY_INV)
    return bw


def _arena_sliding_chars(
    bw: np.ndarray,
    templates: dict[str, np.ndarray],
    *,
    min_conf: float = 0.58,
) -> list[str]:
    detections: list[tuple[int, str, float, int]] = []
    for ch, tpl in templates.items():
        if ch == "dot":
            continue
        th, tw = tpl.shape[:2]
        if tw > bw.shape[1] or th > bw.shape[0]:
            continue
        res = cv2.matchTemplate(bw, tpl, cv2.TM_CCOEFF_NORMED)
        for x in range(res.shape[1]):
            conf = float(res[0, x])
            if conf >= min_conf:
                detections.append((x, ch, conf, tw))
    detections.sort(key=lambda item: (-item[2], item[0]))
    picked: list[tuple[int, str, float]] = []
    for x, ch, conf, tw in detections:
        if any(abs(x - px) < max(8, tw - 2) for px, _, _ in picked):
            continue
        picked.append((x, ch, conf))
    picked.sort(key=lambda item: item[0])
    return [ch for _, ch, _ in picked]


def _arena_chars_to_power(chars: list[str]) -> float | None:
    if "M" in chars:
        digits = [ch for ch in chars[: chars.index("M")] if ch.isdigit()]
    else:
        digits = [ch for ch in chars if ch.isdigit()]
    if len(digits) >= 3:
        digits = digits[:3]
    if len(digits) < 2:
        return None
    num = "".join(digits)
    try:
        value = float(f"{num[0]}.{num[1:]}") if len(num) >= 3 else float(f"{num[0]}.{num[1]}")
    except ValueError:
        return None
    return value if 0.01 <= value <= 99.99 else None


def read_arena_power_patch(patch: np.ndarray) -> float | None:
    templates = _load_arena_digit_templates()
    if not templates:
        return None
    bw = _arena_power_bw(patch)
    if int((bw > 0).sum()) < 40:
        return None
    chars = _arena_sliding_chars(bw, templates)
    return _arena_chars_to_power(chars)


def is_arena_opponents_popup(screen: np.ndarray) -> bool:
    try:
        if matches(
            screen,
            "anchors/arena_opponents_popup.png",
            threshold=0.72,
            region=ARENA_POPUP_TITLE_REGION,
        ):
            return True
        refresh = find_template(
            screen,
            "anchors/arena_free_refresh.png",
            region=(200, 1210, 500, 90),
        )
        return refresh.confidence >= 0.62
    except FileNotFoundError:
        return False


def read_arena_opponent_power(
    screen: np.ndarray,
    row_index: int,
    *,
    region_width: int = 85,
    region_height: int = 28,
) -> float | None:
    _ = region_width
    _ = region_height
    rows = find_arena_power_row_ys(screen)
    if len(rows) <= row_index:
        return None
    patch = _arena_power_patch(screen, rows[row_index])
    value = read_arena_power_patch(patch)
    if value is not None:
        return value
    return _read_arena_power_first_digit(
        screen,
        (
            ARENA_POWER_ROW_SCAN[0],
            rows[row_index] - region_height // 2,
            region_width,
            region_height,
        ),
    )


ARENA_FIRST_DIGIT_DIR = TEMPLATES / "arena"
ARENA_FIRST_DIGIT_X = 191
ARENA_FIRST_DIGIT_W = 17
ARENA_FIRST_DIGIT_H = 28


def _load_arena_first_digit_templates() -> dict[int, np.ndarray]:
    templates: dict[int, np.ndarray] = {}
    if not ARENA_FIRST_DIGIT_DIR.exists():
        return templates
    for path in sorted(ARENA_FIRST_DIGIT_DIR.glob("first_*.png")):
        digit = path.stem.replace("first_", "")
        if not digit.isdigit():
            continue
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            templates[int(digit)] = img
    return templates


def _read_arena_power_first_digit(screen: np.ndarray, region: Region) -> float | None:
    x, y, _w, h = region
    patch = crop(
        screen,
        (ARENA_FIRST_DIGIT_X, y + (h - ARENA_FIRST_DIGIT_H) // 2, ARENA_FIRST_DIGIT_W, ARENA_FIRST_DIGIT_H),
    )
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    if int((gray < 90).sum()) < 25:
        return None
    templates = _load_arena_first_digit_templates()
    if not templates:
        return None
    best_digit, best_conf = -1, 0.0
    runner_conf = 0.0
    for digit, tpl in templates.items():
        th, tw = tpl.shape[:2]
        resized = cv2.resize(gray, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(resized, tpl, cv2.TM_CCOEFF_NORMED)
        conf = float(res[0, 0]) if res.size else 0.0
        if conf > best_conf:
            runner_conf = best_conf
            best_conf, best_digit = conf, digit
        elif conf > runner_conf:
            runner_conf = conf
    if best_digit < 0 or best_conf < 0.55 or (best_conf - runner_conf) < 0.08:
        return None
    return float(best_digit)


def read_arena_power_millions(
    screen: np.ndarray,
    region: Region,
    *,
    min_digit_conf: float = 0.38,
) -> float | None:
    """Lee poder en millones (ej. 4.85M -> 4.85) desde región OCR de Arena."""
    _ = min_digit_conf
    patch = crop(screen, region)
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    templates = _arena_glyph_templates()
    if not templates:
        return None

    digits: list[str] = []
    for x0, width, kind in ARENA_POWER_SLOTS:
        ch, _conf = _match_arena_slot(bw, x0, width, kind, templates)
        if not ch:
            if kind == "M":
                break
            return None
        if kind == "digit":
            digits.append(ch)
        elif ch == "M":
            break

    if len(digits) < 3:
        return None
    num_part = f"{digits[0]}.{digits[1]}{digits[2]}"
    try:
        value = float(num_part)
    except ValueError:
        return None
    return value if 0.01 <= value <= 99.99 else None


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
