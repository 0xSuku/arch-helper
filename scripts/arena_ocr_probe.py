"""Navigate to Arena Challenge popup, run OCR, and report (without attacking)."""
from __future__ import annotations

import sys

from bot import vision
from bot.device import Device
from bot.paths.base import BotContext
from bot.paths.daily import ARENA_OPPONENT_INDEX, DailyPath
from bot.recovery import reconnect_adb


def main() -> int:
    max_power = 4.3
    if len(sys.argv) > 1:
        max_power = float(sys.argv[1])

    device = Device()
    if not reconnect_adb(device):
        print(f"ERROR: ADB not connected ({device.serial})")
        return 2

    ctx = BotContext(device)
    path = object.__new__(DailyPath)
    path.ctx = ctx
    path.arena_max_power = max_power
    path.arena_confirm = False
    path.arena_exit_early = False

    print(f"ADB: {device.serial}")

    if path._is_arena_victory_screen():
        print("Pending victory screen -> Confirm")
        path._tap_arena_confirm()

    if path._is_arena_opponents_popup():
        print("Already on Challenge popup")
    elif path._is_arena_leaderboard():
        print("On Arena leaderboard -> Challenge")
        if not path._opt("events", "arena_challenge", settle=0.8, money_check=False):
            print("ERROR: could not tap Challenge")
            return 1
        if not path._wait_arena_opponents(timeout=12.0):
            print("ERROR: opponents popup did not appear")
            return 1
    else:
        print("Navigating Events -> Arena -> Challenge...")
        if not path._open_arena_rivals_popup("arena_banner"):
            print("ERROR: did not reach opponents popup")
            return 1

    screen = device.screenshot()
    from bot.device import ROOT

    shot = ROOT / "screenshots" / "arena-ocr-probe.png"
    import cv2

    cv2.imwrite(str(shot), screen)

    popup = vision.is_arena_opponents_popup(screen)
    rows = vision.find_arena_power_row_ys(screen)
    print(f"Opponents popup: {popup}")
    print(f"Detected Y rows: {rows}")
    print(f"Screenshot: {shot}")
    print()
    print(f"=== OCR readings (max {max_power}M) ===")

    rivals: dict[int, float | None] = {}
    for i in range(5):
        power = vision.read_arena_opponent_power(screen, i)
        rivals[i + 1] = power
        label = f"{power:.2f}M" if power is not None else "?"
        print(f"  rival #{i + 1}: {label}")

    print()
    print("=== Eligible opponents (#3-#5) ===")
    pick: int | None = None
    for index in range(ARENA_OPPONENT_INDEX, 6):
        power = rivals.get(index)
        if power is None:
            print(f"  rival #{index}: ?")
        elif power < max_power:
            print(f"  rival #{index}: {power:.2f}M  <- eligible")
            if pick is None:
                pick = index
        else:
            print(f"  rival #{index}: {power:.2f}M  (above cap)")

    print()
    if pick is not None:
        print(f"TARGET: rival #{pick} ({rivals[pick]:.2f}M)")
    else:
        print("TARGET: none below cap")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
