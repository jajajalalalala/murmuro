"""Main window: simple left-rail navigation + stacked pages.

Replaces the previous tiny SettingsDialog. The window is the single front
door for everything the user might want to look at — current state,
shortcuts, models. The tray icon stays in charge of process lifecycle;
closing this window only hides it (the app keeps running in the menu bar).

Configuration is persisted whenever any page emits ``preferences_changed``:
each page exposes ``apply_to_config(cfg)`` that mutates a Config draft, the
window collects them, saves to disk, and notifies the host (tray) so the
running ``MurmurApp`` can re-bind the hotkey and rebuild the transcriber.
"""
from __future__ import annotations

import copy
from collections.abc import Callable

from PySide6.QtCore import QSize, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QSystemTrayIcon,
    QWidget,
)

from . import config as config_mod
from ._logging import get_logger
from .app import State
from .pages.about import AboutPage
from .pages.home import HomePage
from .pages.models import ModelsPage
from .pages.shortcuts import ShortcutsPage
from .restart import _default_relaunch, restart_reasons
from .ui.theme import scroll_wrap

_log = get_logger("main_window")


class MainWindow(QMainWindow):
    """Three-page main window: Home / Shortcuts / Models."""

    config_saved = Signal(object)  # Config — host applies + reloads MurmurApp

    def __init__(
        self,
        cfg: config_mod.Config,
        save_config: Callable[[config_mod.Config], None] | None = None,
        parent: QWidget | None = None,
        tray: QSystemTrayIcon | None = None,
        relaunch_fn: Callable[[], None] | None = None,
        restart_delay_ms: int = 800,
    ) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._save_config = save_config or config_mod.save
        # Tray is owned by the host (run_tray); we hold a reference so we
        # can surface a notification before relaunching. None in tests.
        self._tray = tray
        # Injectable for tests so we don't actually re-exec.
        self._relaunch_fn = relaunch_fn or _default_relaunch
        # Window between the tray notification appearing and the relaunch
        # firing. Long enough for the OS to actually paint the banner, short
        # enough that the user doesn't keep typing into the about-to-die app.
        self._restart_delay_ms = restart_delay_ms

        self.setWindowTitle("Murmur")
        self.resize(QSize(760, 520))

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left rail -----------------------------------------------------
        self._nav = QListWidget()
        self._nav.setObjectName("nav")
        self._nav.setFixedWidth(170)
        for label in ("Home", "Shortcuts", "Models", "About"):
            self._nav.addItem(QListWidgetItem(label))
        root.addWidget(self._nav)

        # --- Pages ---------------------------------------------------------
        # Each page is wrapped in a scroll area so a small window can still
        # reach every control — without this, the model list and the
        # language picker get clipped on a 520-tall window and there's no
        # scrollbar to bring them into view.
        self._stack = QStackedWidget()
        self.home_page = HomePage(cfg)
        self.shortcuts_page = ShortcutsPage(cfg)
        self.models_page = ModelsPage(cfg)
        self.about_page = AboutPage(cfg)
        for page in (
            self.home_page, self.shortcuts_page, self.models_page, self.about_page
        ):
            self._stack.addWidget(scroll_wrap(page))
        root.addWidget(self._stack, 1)

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        # Persist + notify on any page edit. The save+reload cost is tiny
        # compared to a full transcription cycle, so we don't debounce.
        for page in (self.home_page, self.shortcuts_page, self.models_page):
            page.preferences_changed.connect(self._persist_changes)

    # ----- Hooks called by the host ---------------------------------------

    def update_state(self, s: State) -> None:
        """Forward a state change from MurmurApp to the Home page."""
        self.home_page.set_state(s)

    def append_transcript(self, text: str) -> None:
        self.home_page.add_transcript(text)

    def reload_config(self, cfg: config_mod.Config) -> None:
        """External config reload (e.g. user hand-edited the TOML)."""
        self._cfg = cfg
        self.home_page.set_config(cfg)
        self.shortcuts_page.set_config(cfg)
        self.models_page.set_config(cfg)
        self.about_page.set_config(cfg)

    # ----- Persistence ----------------------------------------------------

    def _persist_changes(self) -> None:
        # Pages mutate the cfg in place, so snapshot before applying so
        # restart_reasons can compare old vs new.
        previous = copy.deepcopy(self._cfg)
        draft = self._cfg
        draft = self.home_page.apply_to_config(draft)
        draft = self.shortcuts_page.apply_to_config(draft)
        draft = self.models_page.apply_to_config(draft)
        try:
            self._save_config(draft)
        except Exception:  # noqa: BLE001
            _log.exception("failed to save config")
            return
        self._cfg = draft
        self.home_page.set_config(draft)  # refresh the summary line
        self.config_saved.emit(draft)

        # If the change is one we'd rather apply via a clean relaunch
        # (model swap, provider swap, hotkey rebinding), surface a tray
        # notification and auto-relaunch. Previously this was a modal
        # "Restart Now / Cancel" dialog whose default button could be
        # auto-activated by a trailing Enter keypress (the same Enter that
        # had just committed the new hotkey or model selection), making
        # the app appear to vanish without warning. The change is already
        # saved on disk before we get here, so even if the relaunch is
        # somehow missed the new value takes effect on next launch.
        reasons = restart_reasons(previous, draft)
        if reasons:
            self._notify_and_relaunch(reasons[0])

    def _notify_and_relaunch(self, reason: str) -> None:
        """Surface a tray notification and schedule the relaunch.

        Two-step so the OS has a chance to paint the banner before we
        replace the process image. ``_tray`` is None in tests; in that
        case we skip the notification and still schedule the relaunch
        (delay 0 ms in tests via ``restart_delay_ms``).
        """
        if self._tray is not None:
            self._tray.showMessage(
                "Murmur",
                f"Restarting to apply {reason}…",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        QTimer.singleShot(self._restart_delay_ms, self._relaunch_fn)

    # ----- Window behavior ------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        # The app lives in the tray; closing the window just hides it.
        event.ignore()
        self.hide()
