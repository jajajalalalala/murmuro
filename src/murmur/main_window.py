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

from collections.abc import Callable

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from . import config as config_mod
from ._logging import get_logger
from .app import State
from .pages.home import HomePage
from .pages.models import ModelsPage
from .pages.shortcuts import ShortcutsPage

_log = get_logger("main_window")


class MainWindow(QMainWindow):
    """Three-page main window: Home / Shortcuts / Models."""

    config_saved = Signal(object)  # Config — host applies + reloads MurmurApp

    def __init__(
        self,
        cfg: config_mod.Config,
        save_config: Callable[[config_mod.Config], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._save_config = save_config or config_mod.save

        self.setWindowTitle("Murmur")
        self.resize(QSize(760, 520))

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left rail -----------------------------------------------------
        self._nav = QListWidget()
        self._nav.setFixedWidth(160)
        self._nav.setSpacing(2)
        self._nav.setStyleSheet(
            "QListWidget { background: palette(window); border: none; "
            "border-right: 1px solid palette(mid); padding: 12px 0; }"
            "QListWidget::item { padding: 10px 16px; }"
            "QListWidget::item:selected { background: palette(highlight); "
            "color: palette(highlighted-text); border-radius: 4px; }"
        )
        for label in ("Home", "Shortcuts", "Models"):
            self._nav.addItem(QListWidgetItem(label))
        root.addWidget(self._nav)

        # --- Pages ---------------------------------------------------------
        self._stack = QStackedWidget()
        self.home_page = HomePage(cfg)
        self.shortcuts_page = ShortcutsPage(cfg)
        self.models_page = ModelsPage(cfg)
        for page in (self.home_page, self.shortcuts_page, self.models_page):
            self._stack.addWidget(page)
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

    # ----- Persistence ----------------------------------------------------

    def _persist_changes(self) -> None:
        # Build a fresh Config from the current cfg (so every page sees the
        # most recent value when applying).
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

    # ----- Window behavior ------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        # The app lives in the tray; closing the window just hides it.
        event.ignore()
        self.hide()
