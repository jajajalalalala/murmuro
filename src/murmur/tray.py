"""Qt system tray icon for Murmur.

Shows current state via a colored dot and a context menu with Quit.
"""
from __future__ import annotations

import sys
from pathlib import Path

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
from .ui.dialogs import DialogButton, MurmurDialog
from .ui.theme import DARK, LIGHT, apply_theme

_log = get_logger("tray")

# Path to the monochrome μ silhouette we use as the idle tray icon.
# Resolved the same way the main window resolves bundled assets so
# PyInstaller's _MEIPASS path works at runtime.
def _assets_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"


_WORDMARK_DARK_PATH = _assets_dir() / "wordmark_dark.png"


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


def _idle_icon() -> QIcon:
    """Black μ silhouette for the menu-bar idle state, replacing the
    previous gray dot. Recording / transcribing still use colored dots
    so state is visible at a glance even from the menu bar.

    Falls back to the gray dot when the asset is missing — keeps the
    app launchable even if the assets directory wasn't bundled."""
    if _WORDMARK_DARK_PATH.exists():
        return QIcon(str(_WORDMARK_DARK_PATH))
    return _dot_icon("#9aa0a6")


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

    The hint renders through :class:`MurmurDialog` so it visually
    matches the rest of the app — same cream surface, same title-bar
    treatment as the main window. ``QMessageBox`` was the previous
    container but its native chrome made the first-run popup feel
    like a system alert, not part of Murmur.
    """
    status = accessibility_status()
    _log.info("Accessibility status at startup: %s", status.value)
    if status == AccessibilityStatus.GRANTED:
        return
    if status == AccessibilityStatus.UNAVAILABLE:
        return

    open_text = "Open Accessibility settings"
    dialog = MurmurDialog(
        title="Auto-paste needs Accessibility",
        body=(
            "Auto-paste at cursor is enabled but Accessibility isn't "
            "granted. Without it, transcribed text still lands on your "
            "clipboard (press ⌘V to paste manually) — Murmur just can't "
            "simulate the keystroke for you."
        ),
        steps=(
            f"Click {open_text!r} below.",
            "Remove any stale Murmur entry, then drag Murmur.app in or "
            "toggle the existing one ON.",
            "Quit and relaunch Murmur.",
        ),
        buttons=(
            DialogButton("Continue with clipboard only", role="reject"),
            DialogButton(open_text, role="accept", primary=True),
        ),
        parent=parent,
    )
    dialog.exec()
    if dialog.clicked_text == open_text:
        open_accessibility_settings()


def run_tray(cfg: config_mod.Config) -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # Honor the persisted theme preference instead of auto-detecting on
    # every launch — a user who flipped to dark (or stayed on the light
    # default) expects that choice to survive a relaunch.
    apply_theme(app, DARK if cfg.dark_mode else LIGHT)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray not available on this platform.", file=sys.stderr)
        return 1

    if not _ensure_input_monitoring():
        return 2

    if cfg.auto_paste:
        _hint_accessibility_if_denied()

    bridge = _StateBridge()
    tray = QSystemTrayIcon()
    # Idle state uses the μ silhouette in the menu bar (replacing the
    # gray dot the user flagged); active states still get a colored
    # dot so the menu-bar reading is recording / transcribing at a
    # glance.
    tray.setIcon(_idle_icon())
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

    silent_mode_action = QAction("Silent mode (no beeps)")
    silent_mode_action.setCheckable(True)
    silent_mode_action.setChecked(not cfg.play_beeps)
    menu.addAction(silent_mode_action)
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
    # Construct the HUD with a level-provider callable that points at the
    # recorder's live mic-volume reading. We pass a callable rather than the
    # recorder itself so the HUD stays decoupled from audio.py — see
    # RecordingHUD.__init__ for the rationale.
    hud = (
        RecordingHUD(level_provider=lambda: murmur.recorder.current_level)
        if cfg.show_hud
        else None
    )

    def on_state(s: State) -> None:
        _log.info("state -> %s", s.value)
        color, label = STATE_ICONS.get(s, STATE_ICONS[State.IDLE])
        # Idle → μ silhouette; active states (recording, transcribing)
        # → colored dot so a glance at the menu bar tells you what's
        # going on. ``color`` is unused for IDLE here; the silhouette
        # carries the brand instead.
        tray.setIcon(_idle_icon() if s is State.IDLE else _dot_icon(color))
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
        # Sync the tray's silent-mode tick if the change came from the
        # main-window checkbox (or a hand-edit of the TOML). Block our
        # own signal so we don't re-enter the toggle handler.
        silent_mode_action.blockSignals(True)
        silent_mode_action.setChecked(not new_cfg.play_beeps)
        silent_mode_action.blockSignals(False)

    def on_silent_mode_toggled(checked: bool) -> None:
        # Drive the home-page checkbox (single source of truth); its
        # toggled signal fires preferences_changed → MainWindow persists.
        main_window.home_page.play_beeps.setChecked(not checked)

    def on_tray_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left click / double click on the tray icon opens the window.
        # Right click is reserved for the context menu (handled by Qt).
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            open_main_window()

    main_window.config_saved.connect(on_config_saved)
    silent_mode_action.toggled.connect(on_silent_mode_toggled)
    open_window_action.triggered.connect(open_main_window)
    quit_action.triggered.connect(quit_app)
    tray.activated.connect(on_tray_activated)

    return app.exec()
