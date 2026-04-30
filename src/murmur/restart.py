"""Restart helpers.

Some preferences are safest applied by relaunching Murmur from scratch —
pynput's macOS listener can be unstable after a stop/start cycle, and
faster-whisper holds GPU/CPU resources that a clean process drop releases
cleanly.

Previously this module owned a modal "Restart Now / Cancel" QMessageBox
with Restart as the default button. A trailing Enter keypress (often the
one that just committed the new hotkey or model selection) auto-activated
the default button before the user even noticed the dialog, making the
app appear to "quit without notification". The dialog is gone now —
the main window surfaces a tray notification and schedules the relaunch
via QTimer instead. See #37 for the full rationale and #38 for the
v1.1+ hot-reload follow-up that would let us avoid the relaunch entirely.

What stays here:
- ``_default_relaunch``: the actual ``os.execv`` call, importable so the
  main window (and tests) can inject their own.
- ``restart_reasons``: pure diff between two Configs, returning human-
  readable phrases. Lives here (not in main_window) so it's unit-testable
  without importing Qt widgets.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from ._logging import get_logger

_log = get_logger("restart")


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


def restart_reasons(old: object, new: object) -> list[str]:
    """Compare two Configs and return human-readable reasons a restart is
    warranted. Empty list = nothing changed that needs a restart.

    Kept here (and not in main_window) so the logic is unit-testable
    without importing Qt widgets.
    """
    def _norm_backend(b: object) -> object:
        # Pre-#17 callers (and stored configs that haven't been loaded
        # through ``config.load()`` yet) may carry "openai" — treat it
        # as the new "cloud" so equality comparisons line up either way.
        return "cloud" if b == "openai" else b

    reasons: list[str] = []
    old_backend = _norm_backend(getattr(old, "backend", None))
    new_backend = _norm_backend(getattr(new, "backend", None))
    old_provider = getattr(old, "cloud_provider_id", None)
    new_provider = getattr(new, "cloud_provider_id", None)
    # A provider switch counts as a backend switch even if both sides
    # report cfg.backend == "cloud" — the user is moving from openai →
    # groq → custom, which still warrants a clean restart.
    if old_backend != new_backend or (
        old_backend == "cloud"
        and new_backend == "cloud"
        and old_provider != new_provider
    ):
        reasons.append("the model provider change")
    elif (
        old_backend == "local"
        and getattr(getattr(old, "local", None), "model", None)
        != getattr(getattr(new, "local", None), "model", None)
    ) or (
        old_backend == "cloud"
        and getattr(getattr(old, "openai", None), "model", None)
        != getattr(getattr(new, "openai", None), "model", None)
    ):
        reasons.append("the model change")
    if getattr(old, "hotkey", None) != getattr(new, "hotkey", None):
        reasons.append("the shortcut change")
    return reasons
