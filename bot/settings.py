"""Variables de entorno del bot (.env)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_path = ROOT / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


ENV = load_env()
EMULATOR_TYPE = ENV.get("EMULATOR", "mumu").lower()
if EMULATOR_TYPE == "ldplayer":
    EMULATOR_DIR = Path(ENV.get("LDPLAYER_DIR", ENV.get("EMULATOR_DIR", r"D:\LDPlayer\LDPlayer9")))
else:
    EMULATOR_DIR = Path(
        ENV.get(
            "EMULATOR_DIR",
            ENV.get("LDPLAYER_DIR", r"D:\Program Files\Netease\MuMuPlayer\nx_main"),
        )
    )
EMULATOR_INDEX = int(ENV.get("EMULATOR_INDEX", ENV.get("LDPLAYER_INDEX", "0")))
GAME_PACKAGE = ENV.get("GAME_PACKAGE", "com.xq.archeroii")
LDPLAYER_DIR = EMULATOR_DIR

DEFAULT_ADB = EMULATOR_DIR / "adb.exe"
if not DEFAULT_ADB.exists() and EMULATOR_TYPE != "ldplayer":
    fallback = EMULATOR_DIR.parent / "nx_device" / "12.0" / "shell" / "adb.exe"
    if fallback.exists():
        DEFAULT_ADB = fallback

MUMU_BASE_ADB_PORT = 16384
MUMU_PORT_STEP = 32


def default_adb_serial() -> str:
    if "ADB_PORT" in ENV:
        host = ENV.get("ADB_HOST", "127.0.0.1")
        return f"{host}:{ENV['ADB_PORT']}"
    if EMULATOR_TYPE == "ldplayer":
        host = ENV.get("ADB_HOST", "127.0.0.1")
        return f"{host}:{ENV.get('ADB_PORT', '5555')}"
    host = ENV.get("ADB_HOST", "127.0.0.1")
    return f"{host}:{MUMU_BASE_ADB_PORT + EMULATOR_INDEX * MUMU_PORT_STEP}"


DEFAULT_SERIAL = default_adb_serial()
