"""Logging estructurado + dump de capturas ante errores."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .device import Device, ROOT

LOG_DIR = ROOT / "logs"
DUMP_DIR = ROOT / "screenshots" / "dumps"

_configured = False


def get_logger(name: str = "bot") -> logging.Logger:
    global _configured
    if not _configured:
        LOG_DIR.mkdir(exist_ok=True)
        handler_file = logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")
        handler_console = logging.StreamHandler()
        fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
        handler_file.setFormatter(fmt)
        handler_console.setFormatter(fmt)
        root = logging.getLogger("bot")
        root.setLevel(logging.INFO)
        root.addHandler(handler_file)
        root.addHandler(handler_console)
        _configured = True
    return logging.getLogger(f"bot.{name}" if name != "bot" else "bot")


def dump_screen(device: Device, reason: str) -> Path | None:
    try:
        DUMP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = DUMP_DIR / f"{stamp}_{reason}.png"
        device.screenshot(save_as=str(path.relative_to(ROOT / "screenshots")))
        return path
    except Exception:  # noqa: BLE001 - el dump nunca debe romper el flujo
        return None
