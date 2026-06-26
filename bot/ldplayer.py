"""Compatibility: re-exports the unified emulator controller."""
from __future__ import annotations

from .emulator import EmulatorConsole, LdConsole, wait_for_adb

__all__ = ["EmulatorConsole", "LdConsole", "wait_for_adb"]
