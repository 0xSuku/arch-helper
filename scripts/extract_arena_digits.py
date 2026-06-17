"""Extrae templates de dígitos Arena desde screenshots/arena-debug.png."""
from __future__ import annotations

import cv2

from bot.vision import crop

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
IMG = ROOT / "screenshots" / "arena-debug.png"
OUT = ROOT / "templates" / "arena" / "digits"

# (row_y, expected text)
SAMPLES = [
    (572, "8.42M"),
    (688, "6.16M"),
    (880, "5.33M"),
    (972, "6.04M"),
    (1080, "2.63M"),
]


def main() -> None:
    img = cv2.imread(str(IMG))
    if img is None:
        raise SystemExit(f"No image: {IMG}")
    OUT.mkdir(parents=True, exist_ok=True)
    for row_y, text in SAMPLES:
        patch = crop(img, (175, row_y - 18, 95, 36))
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        _, bw = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY_INV)
        col = (bw > 0).sum(axis=0)
        ink = [i for i, v in enumerate(col) if v > bw.shape[0] * 0.12]
        clusters: list[list[int]] = [[ink[0]]]
        for x in ink[1:]:
            if x - clusters[-1][-1] <= 4:
                clusters[-1].append(x)
            else:
                clusters.append([x])
        spans = [(c[0], c[-1] + 1) for c in clusters]
        chars = list(text.replace("M", "M"))
        if len(chars) != len(spans):
            print(f"row {row_y}: cluster count {len(spans)} != {text}")
            continue
        for ch, (x0, x1) in zip(chars, spans):
            sub = bw[:, x0:x1]
            key = "dot" if ch == "." else ch
            path = OUT / f"{key}.png"
            if not path.exists():
                cv2.imwrite(str(path), sub)
                print(f"wrote {path.name} from {text}")


if __name__ == "__main__":
    main()
