"""Confirm-and-restart helper.

Some preferences are safest applied by relaunching Murmur from scratch —
pynput's macOS listener can be unstable after a stop/start cycle, and
faster-whisper holds GPU/CPU resources that a clean process drop releases
cleanly. This module provides the single user-visible prompt for that:
tell the user *why* a restart is being suggested, then give them Restart
or Cancel. The change is already saved either way; cancelling just means
the new value takes effect on the next manual launch.

The relaunch function is injectable so tests can verify the prompt logic
without actually re-execing the Python process.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from ._logging import get_logger

_log = get_logger("restart")

# Default relaunch implementation. Override in tests via ``relaunch_fn``.
def _default_relaunch() -> None:
    _log.info("relaunching: %s %s", sys.executable, sys.argv)
    app = QApplication.instance()
    if app is not None:
        app.quit()
    # ``os.execv`` replaces the current process image — works for both
    # ``python -m murmur`` (sys.executable is the venv python) and a
    # PyInstaller-built ``Murmur.app`` (sys.executable is the bundle's
    # binary, sys.argv[0] is the same).
    os.execv(sys.executable, [sys.executable, *sys.argv])


def confirm_restart(
    reason: str,
    parent: QWidget | None = None,
    relaunch_fn: Callable[[], None] | None = None,
) -> bool:
    """Ask the user whether to restart Murmur now.

    ``reason`` is shown verbatim after "Murmur will restart due to ".
    Pick something the user can connect back to the change they just made:
    ``"the model change"``, ``"the shortcut change"`` etc.

    Returns True if the user accepted (and a relaunch was triggered),
    False if they cancelled.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Restart Murmur")
    box.setText(f"Murmur will restart due to {reason}.")
    box.setInformativeText(
        "Choose Restart Now to apply the change immediately, or Cancel to "
        "keep using the current settings — your change is saved either way "
        "and will take effect the next time Murmur starts."
    )
    restart_btn = box.addButton("Restart Now", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(restart_btn)
    box.exec()
    if box.clickedButton() is restart_btn:
        (relaunch_fn or _default_relaunch)()
        return True
    return False


def restart_reasons(old: object, new: object) -> list[str]:
    """Compare two Configs and return human-readable reasons a restart is
    warranted. Empty list = nothing changed that needs a restart.

    Kept here (and not in main_window) so the logic is unit-testable
    without importing Qt widgets.
    """
    reasons: list[str] = []
    old_backend = getattr(old, "backend", None)
    new_backend = getattr(new, "backend", None)
    if old_backend != new_backend:
        reasons.append("the model provider change")
    elif (
        old_backend == "local"
        and getattr(getattr(old, "local", None), "model", None)
        != getattr(getattr(new, "local", None), "model", None)
    ) or (
        old_backend == "openai"
        and getattr(getattr(old, "openai", None), "model", None)
        != getattr(getattr(new, "openai", None), "model", None)
    ):
        reasons.append("the model change")
    if getattr(old, "hotkey", None) != getattr(new, "hotkey", None):
        reasons.append("the shortcut change")
    return reasons
