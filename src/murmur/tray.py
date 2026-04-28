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
from ._logging import get_logger
from .app import MurmurApp, State
from .hud import RecordingHUD
from .main_window import MainWindow
from .permissions import (
    AccessibilityStatus,
    InputMonitoringStatus,
    accessibility_status,
    input_monitoring_status,
    open_accessibility_settings,
    open_input_monitoring_settings,
    request_input_monitoring,
)
from .ui.theme import apply_theme

_log = get_logger("tray")


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
    paste_request = Signal(str)


def _ensure_input_monitoring(parent=None) -> bool:
    """Block tray startup until the user grants Input Monitoring on macOS.

    First call triggers the system prompt; if the user denied or hasn't acted
    yet, show a dialog with steps and a button that jumps to System Settings.
    Returns True if it's safe to continue, False if we should bail.
    """
    status = input_monitoring_status()
    _log.info("Input Monitoring status at startup: %s", status.value)
    if status == InputMonitoringStatus.GRANTED:
        return True
    if status == InputMonitoringStatus.UNAVAILABLE:
        # Older macOS without IOHIDCheckAccess — let pynput try anyway.
        _log.info("IOHIDCheckAccess unavailable; proceeding without gate")
        return True
    # On UNKNOWN, ask once. macOS only shows the prompt the first time.
    if status == InputMonitoringStatus.UNKNOWN:
        _log.info("requesting Input Monitoring (will trigger system prompt)")
        if request_input_monitoring():
            return True

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Murmur needs Input Monitoring")
    box.setText("Murmur can't see your hotkey yet.")
    box.setInformativeText(
        "macOS requires Input Monitoring permission for global push-to-talk.\n\n"
        "1. Click 'Open System Settings' below.\n"
        "2. If you see an old 'Murmur' entry, REMOVE it (–) before toggling — "
        "every rebuild creates a new identity that the old entry doesn't cover.\n"
        "3. Toggle the current Murmur ON.\n"
        "4. Quit and relaunch Murmur — macOS only re-checks Input Monitoring "
        "at startup.\n\n"
        "Logs: ~/Library/Logs/Murmur/murmur.log"
    )
    open_btn = box.addButton("Open System Settings", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is open_btn:
        open_input_monitoring_settings()
    return False


def _hint_accessibility_if_denied(parent=None) -> None:
    """If auto-paste is on but Accessibility isn't granted, surface a dialog.

    Doesn't block startup — the app still runs (clipboard-only mode is a
    perfectly usable degraded state). The point is to make the missing
    permission visible from a menu-bar app, where stderr warnings are
    invisible and pynput's silent hang would otherwise look like a bug in us.
    """
    status = accessibility_status()
    _log.info("Accessibility status at startup: %s", status.value)
    if status == AccessibilityStatus.GRANTED:
        return
    if status == AccessibilityStatus.UNAVAILABLE:
        return

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Murmur — auto-paste needs Accessibility")
    box.setText("Auto-paste at cursor is enabled but Accessibility isn't granted.")
    box.setInformativeText(
        "Without Accessibility, transcribed text still lands on your clipboard "
        "(press ⌘V to paste manually) but Murmur can't simulate ⌘V for you.\n\n"
        "To enable real auto-paste:\n"
        "1. Click 'Open Accessibility settings' below.\n"
        "2. Remove any stale Murmur entry, then drag dist/Murmur.app in or "
        "toggle the existing one ON.\n"
        "3. Quit and relaunch Murmur."
    )
    open_btn = box.addButton(
        "Open Accessibility settings", QMessageBox.ButtonRole.ActionRole
    )
    box.addButton("Continue with clipboard only", QMessageBox.ButtonRole.AcceptRole)
    box.exec()
    if box.clickedButton() is open_btn:
        open_accessibility_settings()


def run_tray(cfg: config_mod.Config) -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray not available on this platform.", file=sys.stderr)
        return 1

    if not _ensure_input_monitoring():
        return 2

    if cfg.auto_paste:
        _hint_accessibility_if_denied()

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

    open_window_action = QAction("Open Murmur…")
    menu.addAction(open_window_action)
    quit_action = QAction("Quit Murmur")
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()

    main_window = MainWindow(cfg)
    # Open the window on launch so the user lands somewhere they can see —
    # the tray icon alone is easy to miss, especially on first install.
    main_window.show()
    main_window.raise_()
    main_window.activateWindow()
    hud = RecordingHUD() if cfg.show_hud else None

    def on_state(s: State) -> None:
        _log.info("state -> %s", s.value)
        color, label = STATE_ICONS.get(s, STATE_ICONS[State.IDLE])
        tray.setIcon(_dot_icon(color))
        tray.setToolTip(f"Murmur v{__version__} — {label}")
        state_action.setText(label)
        main_window.update_state(s)
        if hud is None:
            return
        if s is State.RECORDING:
            hud.show_at_bottom_center()
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
        main_window.append_transcript(text)

    def on_error_msg(msg: str) -> None:
        _log.error("error: %s", msg)
        tray.showMessage("Murmur error", msg, QSystemTrayIcon.MessageIcon.Critical, 4000)

    def on_paste_request(text: str) -> None:
        # Run from Qt's main thread. CGEventPost from a worker thread is
        # silently filtered on Sonoma+ for ad-hoc-signed bundles — empirical
        # finding from the diagnostic test paste. Same code path as
        # auto-paste but executed on the run-loop thread.
        from .inject import paste_at_cursor
        ok = paste_at_cursor(text)
        _log.info("paste from main thread returned %s (text=%d chars)", ok, len(text))

    bridge.state_changed.connect(on_state)
    bridge.result.connect(on_result)
    bridge.error.connect(on_error_msg)
    bridge.paste_request.connect(on_paste_request)

    murmur = MurmurApp(
        cfg=cfg,
        on_state_change=lambda s: bridge.state_changed.emit(s),
        on_result=lambda t: bridge.result.emit(t),
        on_error=lambda e: bridge.error.emit(str(e)),
        on_paste_request=lambda t: bridge.paste_request.emit(t),
    )

    # Defer hotkey start until after the event loop is running.
    QTimer.singleShot(0, murmur.start)

    def quit_app() -> None:
        murmur.stop()
        app.quit()

    def open_main_window() -> None:
        main_window.show()
        main_window.raise_()
        main_window.activateWindow()

    def on_config_saved(new_cfg: config_mod.Config) -> None:
        murmur.reload_config(new_cfg)
        backend_label.setText(
            f"Backend: {new_cfg.backend}  ·  Hotkey: {new_cfg.hotkey}"
        )

    def on_tray_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left click / double click on the tray icon opens the window.
        # Right click is reserved for the context menu (handled by Qt).
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            open_main_window()

    main_window.config_saved.connect(on_config_saved)
    open_window_action.triggered.connect(open_main_window)
    quit_action.triggered.connect(quit_app)
    tray.activated.connect(on_tray_activated)

    return app.exec()
