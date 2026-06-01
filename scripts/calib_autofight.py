"""Auto-combate de CALIBRACION: elige skills (daño) y esquiva con swipes
hasta detectar una pantalla no reconocida (probable victoria/derrota), que
captura para poder recortar sus anchors. No es el runner final."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot import screens  # noqa: E402
from bot.configs import Coords  # noqa: E402
from bot.device import Device  # noqa: E402
from bot.screens import ScreenId  # noqa: E402
from bot.skills import SkillPicker  # noqa: E402

BUDGET_S = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0


def main() -> None:
    device = Device()
    device.connect()
    picker = SkillPicker()
    coords = Coords.load()
    dodge_down = True
    start = time.time()
    unknown_since = None

    while time.time() - start < BUDGET_S:
        screen = device.screenshot()
        sid = screens.identify(screen)

        if sid == ScreenId.SKILL_SELECT:
            unknown_since = None
            try:
                choice = picker.choose(screen)
                print(f"pick card {choice.index} {choice.category}", flush=True)
                device.tap(choice.tap_x, choice.tap_y)
                time.sleep(1.3)
            except Exception as exc:  # noqa: BLE001
                print(f"pick error: {exc}", flush=True)
                time.sleep(1.0)
            continue

        if sid == ScreenId.DEVIL_DEAL:
            unknown_since = None
            pt = coords.point("battle", "devil_reject")
            print("devil deal -> reject", flush=True)
            device.tap(pt.x, pt.y)
            time.sleep(1.2)
            continue

        if sid == ScreenId.BATTLE:
            unknown_since = None
            if dodge_down:
                device.swipe(450, 820, 450, 1220, 220)
            else:
                device.swipe(450, 1220, 450, 820, 220)
            dodge_down = not dodge_down
            time.sleep(0.35)
            continue

        # Pantalla no reconocida: puede ser transicion o resultado.
        if unknown_since is None:
            unknown_since = time.time()
        cv2.imwrite(str(ROOT / "screenshots" / "calib-unknown.png"), screen)
        if time.time() - unknown_since >= 4.0:
            print("UNKNOWN persistente capturado en screenshots/calib-unknown.png", flush=True)
            return
        time.sleep(1.0)

    print("autofight: presupuesto agotado", flush=True)


if __name__ == "__main__":
    main()
