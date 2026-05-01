"""Process-relaunch helper used by the hotkey-change confirmation modal.

Hotkey changes can't be safely hot-reloaded into the running pynput
listener — see ``main_window`` and #38 for the full story. The user
confirms the relaunch via a "Restart Murmuro to apply?" modal; this
module provides the actual relaunch. Kept separate so the main window
can swap it out in tests.

Why two relaunch strategies:

- ``os.execv`` works in dev mode (``python -m murmuro``) — replaces the
  process image cleanly.
- For a PyInstaller-built ``Murmuro.app`` it does **not** work in
  practice. macOS LaunchServices keeps the parent's Process Serial
  Number on the new process and silently refuses to register it as a
  foreground app, so the relaunch appears to do nothing. The fix is to
  spawn a fresh launch via ``open -na <bundle>`` and exit.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtWidgets import QApplication

from ._logging import get_logger

_log = get_logger("restart")


def _find_app_bundle_root() -> str | None:
    """Walk up from ``sys.executable`` to find a ``.app`` ancestor.

    Returns the bundle path (e.g. ``/Applications/Murmuro.app``) or
    ``None`` when not running from a bundle (dev mode, plain Python).
    """
    if sys.platform != "darwin":
        return None
    path = os.path.dirname(os.path.abspath(sys.executable))
    # Cap the walk at a reasonable depth so a pathological symlink can't
    # spin us forever.
    for _ in range(8):
        if path.endswith(".app"):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    return None


def _default_relaunch() -> None:
    bundle = _find_app_bundle_root()
    _log.info(
        "relaunching: bundle=%s executable=%s argv=%s",
        bundle, sys.executable, sys.argv,
    )

    app = QApplication.instance()
    if app is not None:
        app.quit()

    if bundle is not None:
        # macOS .app: ask LaunchServices to start a new instance with a
        # fresh PSN. ``-n`` forces a new instance even if the app is
        # already running, ``-a`` would expect a name; ``-na <path>``
        # is the canonical "relaunch myself" incantation.
        subprocess.Popen(["open", "-na", bundle])
        # Exit so the parent doesn't linger and so macOS's
        # "duplicate instance" UI doesn't appear.
        sys.exit(0)

    # Dev mode (and any non-darwin path): replace the process image.
    os.execv(sys.executable, [sys.executable, *sys.argv])
