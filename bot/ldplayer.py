"""Compatibilidad: reexporta el controlador unificado del emulador."""
from __future__ import annotations

from .emulator import EmulatorConsole, LdConsole, wait_for_adb

__all__ = ["EmulatorConsole", "LdConsole", "wait_for_adb"]
