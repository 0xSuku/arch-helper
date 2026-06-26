"""Extract Arena digit templates from a capture with known values."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from bot.vision import _arena_power_bw, crop

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMG = ROOT / "screenshots" / "arena-ocr-probe.png"
OUT = ROOT / "templates" / "arena" / "digits"

PATCH = (100, -14, 140, 32)

# (row_y, text, digit spans x0-x1)
SAMPLES: list[tuple[int, str, list[tuple[int, int]]]] = [
    (488, "8.33", [(67, 81), (93, 105), (109, 121)]),
    (688, "10.62", [(60, 70), (75, 89), (100, 114), (116, 122)]),
    (888, "3.32", [(68, 80), (93, 105), (108, 122)]),
    (1088, "5.14", [(68, 80), (93, 103), (108, 122)]),
    (1308, "1.55", [(73, 78), (93, 105), (109, 121)]),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, default=DEFAULT_IMG)
    args = parser.parse_args()

    img = cv2.imread(str(args.image))
    if img is None:
        raise SystemExit(f"No image: {args.image}")
    OUT.mkdir(parents=True, exist_ok=True)
    px, py_off, pw, ph = PATCH

    for row_y, text, spans in SAMPLES:
        bw = _arena_power_bw(crop(img, (px, row_y + py_off, pw, ph)))
        digits = [c for c in text if c.isdigit()]
        for (x0, x1), ch in zip(spans, digits):
            glyph = bw[:, x0:x1]
            cv2.imwrite(str(OUT / f"{ch}.png"), glyph)
            cv2.imwrite(str(OUT / f"{ch}_{row_y}.png"), glyph)
            print(f"wrote {ch} from row {row_y} ({text})")

    ref_bw = _arena_power_bw(crop(img, (px, SAMPLES[-1][0] + py_off, pw, ph)))
    cv2.imwrite(str(OUT / "dot.png"), ref_bw[:, 84:90])
    cv2.imwrite(str(OUT / "M.png"), ref_bw[:, 125:130])
    print("wrote dot.png M.png")


if __name__ == "__main__":
    main()
