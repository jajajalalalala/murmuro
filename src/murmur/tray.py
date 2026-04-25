"""Qt system tray icon for Murmur.

Shows current state via a colored dot and a context menu with Quit.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import __version__
from . import config as config_mod
from .app import MurmurApp, State
from .hud import RecordingHUD
from .permissions import (
    InputMonitoringStatus,
    input_monitoring_status,
    open_input_monitoring_settings,
    request_input_monitoring,
)
from .settings_dialog import SettingsDialog


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


def _ensure_input_monitoring(parent=None) -> bool:
    """Block tray startup until the user grants Input Monitoring on macOS.

    First call triggers the system prompt; if the user denied or hasn't acted
    yet, show a dialog with steps and a button that jumps to System Settings.
    Returns True if it's safe to continue, False if we should bail.
    """
    status = input_monitoring_status()
    if status == InputMonitoringStatus.GRANTED:
        return True
    if status == InputMonitoringStatus.UNAVAILABLE:
        # Older macOS without IOHIDCheckAccess — let pynput try anyway.
        return True
    # On UNKNOWN, ask once. macOS only shows the prompt the first time.
    if status == InputMonitoringStatus.UNKNOWN and request_input_monitoring():
        return True

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Murmur needs Input Monitoring")
    box.setText("Murmur can't see your hotkey yet.")
    box.setInformativeText(
        "macOS requires Input Monitoring permission for global push-to-talk.\n\n"
        "1. Click 'Open System Settings' below\n"
        "2. Toggle Murmur (or your terminal, if you ran ./start.sh) ON\n"
        "3. Quit and relaunch Murmur — macOS only re-checks at startup."
    )
    open_btn = box.addButton("Open System Settings", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is open_btn:
        open_input_monitoring_settings()
    return False


def run_tray(cfg: config_mod.Config) -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray not available on this platform.", file=sys.stderr)
        return 1

    if not _ensure_input_monitoring():
        return 2

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

    settings_action = QAction("Settings…")
    menu.addAction(settings_action)
    quit_action = QAction("Quit Murmur")
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()

    hud = RecordingHUD()

    def on_state(s: State) -> None:
        color, label = STATE_ICONS.get(s, STATE_ICONS[State.IDLE])
        tray.setIcon(_dot_icon(color))
        tray.setToolTip(f"Murmur v{__version__} — {label}")
        state_action.setText(label)
        if s is State.RECORDING:
            hud.show_at_top_center()
        else:
            hud.hide()

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

    def open_settings() -> None:
        dlg = SettingsDialog(murmur.cfg)
        if dlg.exec() == dlg.DialogCode.Accepted:
            new_cfg = dlg.updated_config()
            try:
                config_mod.save(new_cfg)
            except Exception as e:  # noqa: BLE001
                tray.showMessage(
                    "Murmur — settings",
                    f"Couldn't save config: {e}",
                    QSystemTrayIcon.MessageIcon.Critical,
                    4000,
                )
                return
            murmur.reload_config(new_cfg)
            backend_label.setText(
                f"Backend: {new_cfg.backend}  ·  Hotkey: {new_cfg.hotkey}"
            )
            tray.showMessage(
                "Murmur",
                f"Settings saved. Hotkey: {new_cfg.hotkey}",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )

    settings_action.triggered.connect(open_settings)
    quit_action.triggered.connect(quit_app)

    return app.exec()
