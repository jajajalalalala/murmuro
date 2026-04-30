"""Main window: simple left-rail navigation + stacked pages.

Replaces the previous tiny SettingsDialog. The window is the single front
door for everything the user might want to look at — current state,
shortcuts, models. The tray icon stays in charge of process lifecycle;
closing this window only hides it (the app keeps running in the menu bar).

Configuration is persisted whenever any page emits ``preferences_changed``:
each page exposes ``apply_to_config(cfg)`` that mutates a Config draft, the
window collects them, saves to disk, and notifies the host (tray) so the
running ``MurmurApp`` can re-bind the model/provider in-process.

Hotkey changes are the one axis we can't safely hot-reload (#38). Two
attempts (PR #47 stop+start, PR #49 in-place rebind) both failed in the
trusted ``Murmur.app`` for reasons that don't reproduce in offscreen
tests. Instead we show an explicit "Restart Murmur to apply?" modal with
Cancel as the default button — so a stray Enter (from committing the new
hotkey) doesn't auto-fire the restart.
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import config as config_mod
from ._logging import get_logger
from .app import State
from .pages.about import AboutPage
from .pages.home import HomePage
from .pages.models import ModelsPage
from .pages.shortcuts import ShortcutsPage
from .restart import _default_relaunch
from .ui.theme import scroll_wrap

_log = get_logger("main_window")

# The icon ships with the repo at assets/icon.png — resolve once so unit
# tests don't have to mock anything when constructing the main window.
_ICON_PATH = Path(__file__).resolve().parents[2] / "assets" / "icon.png"


class MainWindow(QMainWindow):
    """Three-page main window: Home / Shortcuts / Models."""

    config_saved = Signal(object)  # Config — host applies + reloads MurmurApp

    def __init__(
        self,
        cfg: config_mod.Config,
        save_config: Callable[[config_mod.Config], None] | None = None,
        parent: QWidget | None = None,
        relaunch_fn: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._save_config = save_config or config_mod.save
        # Injectable for tests so we don't actually re-exec.
        self._relaunch_fn = relaunch_fn or _default_relaunch

        self.setWindowTitle("Murmur")
        self.resize(QSize(760, 520))

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left rail (brand header + nav list) --------------------------
        rail = QWidget()
        rail.setObjectName("rail")
        rail.setFixedWidth(170)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(0)

        rail_layout.addWidget(self._build_brand_header())

        self._nav = QListWidget()
        self._nav.setObjectName("nav")
        for label in ("Home", "Shortcuts", "Models", "About"):
            self._nav.addItem(QListWidgetItem(label))
        rail_layout.addWidget(self._nav, 1)

        root.addWidget(rail)

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

    # ----- Construction helpers -------------------------------------------

    def _build_brand_header(self) -> QWidget:
        """Top-of-rail brand bar: app icon + 'Murmur' wordmark.

        Pulled into its own factory so a future tweak (replacing the
        wordmark with a logotype, adding a version line, etc.) lands in
        one place. Falls back gracefully when the icon asset is missing
        — important for unit tests that don't always have repo assets
        on disk.
        """
        header = QWidget()
        header.setObjectName("brandHeader")
        header.setFixedHeight(56)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)

        icon_label = QLabel()
        icon_label.setFixedSize(28, 28)
        if _ICON_PATH.exists():
            pixmap = QPixmap(str(_ICON_PATH)).scaled(
                28, 28,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon_label.setPixmap(pixmap)
        layout.addWidget(icon_label)

        wordmark = QLabel("Murmur")
        wordmark.setObjectName("brandText")
        layout.addWidget(wordmark)
        layout.addStretch(1)
        return header

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
        # Snapshot before applying so we can revert cleanly on cancel.
        # Pages mutate the cfg in place, so without this snapshot the
        # "previous" hotkey value is already overwritten by the time we
        # get to the diff check.
        previous = copy.deepcopy(self._cfg)
        draft = self._cfg
        draft = self.home_page.apply_to_config(draft)
        draft = self.shortcuts_page.apply_to_config(draft)
        draft = self.models_page.apply_to_config(draft)
        hotkey_changed = previous.hotkey != draft.hotkey

        if hotkey_changed and not self._confirm_hotkey_restart():
            # Cancel: undo the in-memory mutation and reset the shortcuts
            # widget so the displayed hotkey matches what the running app
            # is actually bound to. Any other changes the user made in
            # this same save (rare — pages emit on each edit) revert too,
            # which matches the "abandon this save attempt" mental model.
            self._cfg = previous
            self.shortcuts_page.set_config(previous)
            self.home_page.set_config(previous)
            self.models_page.set_config(previous)
            return

        try:
            self._save_config(draft)
        except Exception:  # noqa: BLE001
            _log.exception("failed to save config")
            self._cfg = previous
            return
        self._cfg = draft
        self.home_page.set_config(draft)  # refresh the summary line
        # Model / provider changes ride MurmurApp.reload_config's selective
        # transcriber drop (#44, #46) — the next push-to-talk press picks
        # up the new config without a relaunch.
        self.config_saved.emit(draft)

        if hotkey_changed:
            # Defer the relaunch so the QMessageBox fully dismisses and
            # this _persist_changes call unwinds before the process image
            # is replaced. ``QTimer.singleShot(0, ...)`` runs on the next
            # event-loop iteration, by which point the modal stack is
            # clean.
            QTimer.singleShot(0, self._relaunch_fn)

    def _confirm_hotkey_restart(self) -> bool:
        """Show the restart-confirmation modal, return True iff the user
        clicked Restart.

        Cancel is the default button so a stray Enter — often the one
        that just committed the new hotkey via the recorder — dismisses
        the dialog harmlessly. That was the original PR #39 motivation:
        a Restart-default modal auto-fired before the user even saw it.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Restart Murmur?")
        box.setText("Apply the new hotkey?")
        box.setInformativeText(
            "Murmur needs to restart for the new hotkey to take effect.\n\n"
            "Choose Cancel to keep using your previous hotkey — your "
            "change will be discarded."
        )
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        restart_btn = box.addButton(
            "Restart now", QMessageBox.ButtonRole.AcceptRole
        )
        # Default = Cancel: a stray Enter must not auto-fire the relaunch.
        box.setDefaultButton(cancel_btn)
        box.exec()
        return box.clickedButton() is restart_btn

    # ----- Window behavior ------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        # The app lives in the tray; closing the window just hides it.
        event.ignore()
        self.hide()
