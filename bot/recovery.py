"""Recovery when the emulator or game hangs (infinite loading, taps have no effect)."""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path

from .device import Device, sleep
from .emulator import EmulatorConsole
from .log import get_logger
from .screens import ScreenId

log = get_logger("recovery")

_PLATFORM_ADB = Path(r"C:\Program Files (x86)\Android\platform-tools\adb.exe")
PORT_WAIT_S = 20.0
PORT_WAIT_AFTER_RESTART_S = 30.0
CONNECT_ATTEMPTS = 5
CONNECT_DELAY_S = 1.5


def _parse_serial(serial: str) -> tuple[str, int]:
    host, port = serial.rsplit(":", 1)
    return host, int(port)


def _adb_port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _kill_adb_servers(*adb_bins: Path) -> None:
    seen: set[str] = set()
    for adb in adb_bins:
        if not adb.exists():
            continue
        key = str(adb.resolve())
        if key in seen:
            continue
        seen.add(key)
        subprocess.run([str(adb), "kill-server"], check=False, capture_output=True)


def _start_adb_server(adb_path: Path) -> None:
    subprocess.run([str(adb_path), "start-server"], check=False, capture_output=True)


def _wait_for_adb_port(
    host: str,
    port: int,
    *,
    timeout: float,
    poll: float = 2.0,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _adb_port_open(host, port):
            log.info("ADB port %s:%d open", host, port)
            return True
        sleep(poll)
    return False


def _sync_device_serial(device: Device, console: EmulatorConsole) -> None:
    serial = console.default_serial()
    if serial != device.serial:
        log.info("ADB serial updated: %s -> %s", device.serial, serial)
        device.serial = serial


def _try_connect(device: Device, console: EmulatorConsole) -> bool:
    console.connect_adb()
    subprocess.run(
        [str(device.adb_path), "connect", device.serial],
        check=False,
        capture_output=True,
    )
    if not device.is_connected():
        return False
    try:
        device.screenshot(retry_reconnect=False)
        return True
    except RuntimeError:
        return False


def reconnect_adb(
    device: Device,
    *,
    attempts: int = CONNECT_ATTEMPTS,
    delay: float = CONNECT_DELAY_S,
    wait_port: bool = True,
    port_timeout: float = PORT_WAIT_S,
    port_timeout_after_restart: float = PORT_WAIT_AFTER_RESTART_S,
    restart_emulator: bool = True,
    restart_ldplayer: bool | None = None,
) -> bool:
    """Reconnect ADB; with MuMu uses MuMuManager connect when needed."""
    if restart_ldplayer is not None:
        restart_emulator = restart_ldplayer

    console = EmulatorConsole()
    _sync_device_serial(device, console)
    host, port = _parse_serial(device.serial)

    if device.is_connected():
        try:
            device.screenshot(retry_reconnect=False)
            log.info("ADB already connected (%s)", device.serial)
            return True
        except RuntimeError:
            log.warning("ADB listed but screencap failed; reconnecting...")

    def _prepare_adb() -> None:
        _kill_adb_servers(device.adb_path, _PLATFORM_ADB)
        _start_adb_server(device.adb_path)

    def _ensure_emulator_up() -> None:
        if console.is_running():
            return
        log.warning("%s stopped; launching (index=%d)", console.display_name, console.index)
        console.launch()
        sleep(8.0)
        _sync_device_serial(device, console)

    def _wait_port(phase: str, timeout: float) -> bool:
        if not wait_port:
            return True
        _sync_device_serial(device, console)
        host, port = _parse_serial(device.serial)
        log.info("%s: waiting for ADB port %s (up to %.0fs)...", phase, device.serial, timeout)
        return _wait_for_adb_port(host, port, timeout=timeout, poll=1.0)

    _prepare_adb()
    _ensure_emulator_up()
    if not _wait_port("Reconnect", port_timeout):
        if restart_emulator and console.is_running():
            log.warning(
                "ADB port did not open; soft restart %s (shutdown + launch)",
                console.display_name,
            )
            console.quit()
            sleep(4.0)
            console.launch()
            sleep(10.0)
            _sync_device_serial(device, console)
            _prepare_adb()
            if not _wait_port(f"After relaunching {console.display_name}", port_timeout_after_restart):
                log.error(
                    "ADB port still closed (%s). Check ADB in the emulator and retry reconnect.",
                    device.serial,
                )
                return False
        elif not restart_emulator:
            log.error("ADB port %s:%d not responding", host, port)
            return False

    for n in range(attempts):
        log.info("Reconnecting ADB (%d/%d) -> %s", n + 1, attempts, device.serial)
        if _try_connect(device, console):
            log.info("ADB reconnected (%s)", device.serial)
            return True
        sleep(delay)

    host, port = _parse_serial(device.serial)
    log.error(
        "Could not reconnect ADB to %s. %s=%s, port=%s",
        device.serial,
        console.display_name,
        "running" if console.is_running() else "stopped",
        "open" if _adb_port_open(host, port) else "closed",
    )
    return False


def reboot_emulator_and_wait_lobby(
    device: Device,
    *,
    console: EmulatorConsole | None = None,
    adb_timeout: float = 60.0,
    lobby_timeout: float = 90.0,
) -> bool:
    """Reboot emulator, reconnect ADB, launch game, and wait for lobby."""
    emu = console or EmulatorConsole()
    if not emu.tool.exists():
        log.error(
            "Could not find %s at %s. Restart the emulator manually.",
            emu.tool.name,
            emu.tool,
        )
        return False

    emu.reboot()
    sleep(5.0)
    _sync_device_serial(device, emu)

    log.info("Waiting for ADB after reboot (up to %.0fs)...", adb_timeout)
    if not reconnect_adb(
        device,
        attempts=6,
        delay=CONNECT_DELAY_S,
        wait_port=True,
        port_timeout=adb_timeout,
        port_timeout_after_restart=adb_timeout,
        restart_emulator=False,
    ):
        log.error("ADB did not respond after rebooting %s. Open the emulator manually.", emu.display_name)
        return False

    emu.run_app()
    sleep(8.0)

    deadline = time.time() + lobby_timeout
    while time.time() < deadline:
        try:
            from . import screens

            if screens.identify(device.screenshot()) == ScreenId.LOBBY:
                log.info("Lobby detected after recovery.")
                return True
        except RuntimeError:
            pass
        sleep(2.0)

    log.warning(
        "%s rebooted but did not reach lobby within %.0fs. "
        "Leave the game on the lobby and retry the claim.",
        emu.display_name,
        lobby_timeout,
    )
    return False


reboot_ldplayer_and_wait_lobby = reboot_emulator_and_wait_lobby


def adb_status(device: Device) -> dict[str, str | bool]:
    console = EmulatorConsole()
    _sync_device_serial(device, console)
    host, port = _parse_serial(device.serial)
    return {
        "emulator": console.display_name,
        "backend": console.backend,
        "running": console.is_running(),
        "port_open": _adb_port_open(host, port),
        "adb_listed": device.is_connected(),
        "serial": device.serial,
        "ldplayer": "running" if console.is_running() else "stopped",
    }
