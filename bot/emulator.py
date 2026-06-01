"""Control del emulador (MuMu Player 12 por defecto, LDPlayer legacy)."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .log import get_logger
from .settings import (
    DEFAULT_ADB,
    EMULATOR_DIR,
    EMULATOR_INDEX,
    EMULATOR_TYPE,
    ENV,
    GAME_PACKAGE,
    MUMU_BASE_ADB_PORT,
    MUMU_PORT_STEP,
)

log = get_logger("emulator")


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.debug("JSON invalido del emulador: %s", text[:200])
        return {}
    return data if isinstance(data, dict) else {}


class EmulatorConsole:
    def __init__(
        self,
        *,
        backend: str = EMULATOR_TYPE,
        tool_dir: Path = EMULATOR_DIR,
        index: int = EMULATOR_INDEX,
        game_package: str = GAME_PACKAGE,
    ) -> None:
        self.backend = backend.lower()
        self.tool_dir = Path(tool_dir)
        self.index = index
        self.game_package = game_package
        if self.backend == "ldplayer":
            self.tool = self.tool_dir / "ldconsole.exe"
        else:
            self.tool = self.tool_dir / "MuMuManager.exe"

    @property
    def ldconsole(self) -> Path:
        return self.tool

    def _run(self, *args: str) -> str:
        result = subprocess.run(
            [str(self.tool), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if result.returncode != 0 and err:
            log.debug("%s %s -> rc=%s stderr=%s", self.tool.name, " ".join(args), result.returncode, err)
        return out

    def _mumu_info(self) -> dict:
        return _parse_json(self._run("info", "-v", str(self.index)))

    def adb_endpoint(self) -> tuple[str, int]:
        if self.backend == "ldplayer":
            host = ENV.get("ADB_HOST", "127.0.0.1")
            port = int(ENV.get("ADB_PORT", "5555"))
            return host, port
        info = self._mumu_info()
        host = str(info.get("adb_host_ip") or info.get("adb_host") or "127.0.0.1")
        port = info.get("adb_port")
        if port:
            return host, int(port)
        return "127.0.0.1", MUMU_BASE_ADB_PORT + self.index * MUMU_PORT_STEP

    def default_serial(self) -> str:
        if "ADB_PORT" in ENV:
            host = ENV.get("ADB_HOST", "127.0.0.1")
            return f"{host}:{ENV['ADB_PORT']}"
        host, port = self.adb_endpoint()
        return f"{host}:{port}"

    def is_running(self) -> bool:
        if self.backend == "ldplayer":
            return self._run("isrunning", "--index", str(self.index)) == "running"
        info = self._mumu_info()
        return bool(info.get("is_android_started") or info.get("is_process_started"))

    def launch(self) -> None:
        log.info("Lanzando %s (index=%d)...", self.display_name, self.index)
        if self.backend == "ldplayer":
            self._run("launch", "--index", str(self.index))
        else:
            self._run("control", "-v", str(self.index), "launch")

    def quit(self) -> None:
        log.info("Cerrando %s (index=%d)...", self.display_name, self.index)
        if self.backend == "ldplayer":
            self._run("quit", "--index", str(self.index))
        else:
            self._run("control", "-v", str(self.index), "shutdown")

    def reboot(self) -> None:
        log.info("Reiniciando %s (index=%d)...", self.display_name, self.index)
        if self.backend == "ldplayer":
            self._run("reboot", "--index", str(self.index))
        else:
            self._run("control", "-v", str(self.index), "restart")

    def run_app(self, package: str | None = None) -> None:
        pkg = package or self.game_package
        log.info("Abriendo %s en %s...", pkg, self.display_name)
        if self.backend == "ldplayer":
            self._run("runapp", "--index", str(self.index), "--packagename", pkg)
        else:
            self._run("control", "-v", str(self.index), "app", "launch", "-pkg", pkg)

    def kill_app(self, package: str | None = None) -> None:
        pkg = package or self.game_package
        if self.backend == "ldplayer":
            self._run("killapp", "--index", str(self.index), "--packagename", pkg)
        else:
            self._run("control", "-v", str(self.index), "app", "close", "-pkg", pkg)

    def connect_adb(self) -> bool:
        if self.backend == "ldplayer":
            host, port = self.adb_endpoint()
            subprocess.run(
                [str(DEFAULT_ADB), "connect", f"{host}:{port}"],
                check=False,
                capture_output=True,
            )
            return True
        data = _parse_json(self._run("adb", "-v", str(self.index), "-c", "connect"))
        output = (data.get("cmd_output") or "").lower()
        return "connected" in output or "already connected" in output

    @property
    def display_name(self) -> str:
        return "LDPlayer" if self.backend == "ldplayer" else "MuMu Player"


LdConsole = EmulatorConsole


def wait_for_adb(
    adb_path: Path = DEFAULT_ADB,
    serial: str | None = None,
    timeout: float = 180.0,
    poll: float = 2.0,
) -> bool:
    target = serial or EmulatorConsole().default_serial()
    deadline = time.time() + timeout
    console = EmulatorConsole()
    while time.time() < deadline:
        console.connect_adb()
        subprocess.run([str(adb_path), "connect", target], check=False, capture_output=True)
        result = subprocess.run(
            [str(adb_path), "devices"],
            check=False,
            capture_output=True,
            text=True,
        )
        if f"{target}\tdevice" in (result.stdout or ""):
            return True
        time.sleep(poll)
    return False
