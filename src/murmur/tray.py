"""Qt system tray icon for Murmur.

Shows current state via a colored dot and a context menu with Quit.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import __version__
from . import config as config_mod
from .app import MurmurApp, State


def _dot_icon(color: str) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QColor(20, 20, 20, 180))
    p.drawEllipse(8, 8, 48, 48)
    p.end()
    return QIcon(pm)


STATE_ICONS = {
    State.IDLE: ("#9aa0a6", "Idle"),
    State.RECORDING: ("#e53935", "Recording…"),
    State.TRANSCRIBING: ("#fbc02d", "Transcribing…"),
}


class _StateBridge(QObject):
    """Marshal MurmurApp's worker-thread events onto the Qt main thread."""

    state_changed = Signal(object)  # State enum
    result = Signal(str)
    error = Signal(str)


def run_tray(cfg: config_mod.Config) -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray not available on this platform.", file=sys.stderr)
        return 1

    bridge = _StateBridge()
    tray = QSystemTrayIcon()
    tray.setIcon(_dot_icon(STATE_ICONS[State.IDLE][0]))
    tray.setToolTip(f"Murmur v{__version__} — idle")

    menu = QMenu()
    state_action = QAction("Idle")
    state_action.setEnabled(False)
    menu.addAction(state_action)
    menu.addSeparator()

    backend_label = QAction(f"Backend: {cfg.backend}  ·  Hotkey: {cfg.hotkey}")
    backend_label.setEnabled(False)
    menu.addAction(backend_label)
    menu.addSeparator()

    quit_action = QAction("Quit Murmur")
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()

    def on_state(s: State) -> None:
        color, label = STATE_ICONS.get(s, STATE_ICONS[State.IDLE])
        tray.setIcon(_dot_icon(color))
        tray.setToolTip(f"Murmur v{__version__} — {label}")
        state_action.setText(label)

    def on_result(text: str) -> None:
        preview = text if len(text) <= 60 else text[:57] + "..."
        tray.showMessage(
            "Murmur",
            f"Copied: {preview}",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def on_error_msg(msg: str) -> None:
        tray.showMessage("Murmur error", msg, QSystemTrayIcon.MessageIcon.Critical, 4000)

    bridge.state_changed.connect(on_state)
    bridge.result.connect(on_result)
    bridge.error.connect(on_error_msg)

    murmur = MurmurApp(
        cfg=cfg,
        on_state_change=lambda s: bridge.state_changed.emit(s),
        on_result=lambda t: bridge.result.emit(t),
        on_error=lambda e: bridge.error.emit(str(e)),
    )

    # Defer hotkey start until after the event loop is running.
    QTimer.singleShot(0, murmur.start)

    def quit_app() -> None:
        murmur.stop()
        app.quit()

    quit_action.triggered.connect(quit_app)

    return app.exec()
