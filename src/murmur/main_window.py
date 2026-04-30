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
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
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
from .ui.theme import DARK, LIGHT, apply_theme, scroll_wrap

_log = get_logger("main_window")


def _assets_dir() -> Path:
    """Return the directory containing bundled icon assets.

    Two cases:
    - Dev / installed-via-pip: ``__file__`` lives in ``src/murmur/`` and
      assets is at the repo root (parents[2] = repo root).
    - PyInstaller bundle: ``sys._MEIPASS`` points at the runtime extract
      dir; ``--add-data assets:assets`` puts the assets directory there.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"


_ICON_PATH = _assets_dir() / "icon.png"
_WORDMARK_DARK_PATH = _assets_dir() / "wordmark_dark.png"
_WORDMARK_LIGHT_PATH = _assets_dir() / "wordmark_light.png"


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

        # Title hidden — we hide the macOS title bar entirely via NSWindow
        # (see _configure_macos_titlebar) so content extends to the very
        # top of the window. Traffic lights stay; the "Murmur" text bar
        # the user flagged is gone.
        self.setWindowTitle("Murmur")
        # Bigger default — 760×520 felt cramped, especially the Models
        # page where a long list and the action buttons compete for the
        # same vertical space.
        self.resize(QSize(940, 660))

        # Track whether we've applied the macOS title-bar styling yet so
        # we only do it once on first show (winId() needs a real native
        # window, which doesn't exist until showEvent).
        self._titlebar_styled = False

        # Theme state. We default to LIGHT (per user request) but remember
        # the active palette so the toggle button can flip it.
        self._active_palette = LIGHT

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left rail (brand header + top nav + bottom row) -------------
        rail = QWidget()
        rail.setObjectName("rail")
        rail.setFixedWidth(170)
        rail_layout = QVBoxLayout(rail)
        # Bottom margin pulls the About row up off the window edge so
        # its text doesn't read as truncated against the bezel.
        rail_layout.setContentsMargins(0, 0, 0, 12)
        rail_layout.setSpacing(0)

        rail_layout.addWidget(self._build_brand_header())

        # Top nav — Home, Shortcuts, Models. About lives at the bottom of
        # the rail (per user feedback) so it's a quick eye-jump and
        # doesn't compete with the primary destinations.
        self._nav_top = QListWidget()
        self._nav_top.setObjectName("nav")
        for label in ("Home", "Shortcuts", "Models"):
            self._nav_top.addItem(QListWidgetItem(label))
        rail_layout.addWidget(self._nav_top, 1)

        # Bottom row: About + theme toggle, separated by a thin divider
        # so the bottom area reads as its own section visually.
        rail_layout.addWidget(self._build_bottom_rail_section())

        root.addWidget(rail)

        # --- Pages ---------------------------------------------------------
        # Each page is wrapped in a scroll area so a small window can still
        # reach every control — without this, the model list and the
        # language picker get clipped on a small window and there's no
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

        # Wire nav: top list selects pages 0/1/2; the bottom About button
        # selects page 3 and clears the top list's selection so we never
        # show two highlights at once.
        self._nav_top.currentRowChanged.connect(self._on_top_nav_changed)
        self._nav_top.setCurrentRow(0)

        # Persist + notify on any page edit. The save+reload cost is tiny
        # compared to a full transcription cycle, so we don't debounce.
        for page in (self.home_page, self.shortcuts_page, self.models_page):
            page.preferences_changed.connect(self._persist_changes)

        # Theme toggle lives on the Home page now (not the rail) — it's
        # really a preference, not chrome. The page emits a request,
        # MainWindow re-applies the global stylesheet.
        self.home_page.theme_toggle_requested.connect(self.set_theme)

    # ----- Construction helpers -------------------------------------------

    def _build_brand_header(self) -> QWidget:
        """Top-of-rail brand bar: μ silhouette + 'Murmur' wordmark.

        The orange-square app icon lives in Finder / the Dock; for the
        in-app rail we use a quieter monochrome μ silhouette that
        adapts to the active theme (dark glyph on light surfaces, light
        glyph on dark). The orange square next to the wordmark felt
        louder than the rest of the chrome.

        With the macOS title bar hidden, the traffic-light buttons
        (close / minimize / maximize) overlay the top-left of the
        window — roughly 70 px wide × 28 px tall. The brand header
        reserves 28 px of top padding so its content sits below the
        traffic-light strip and doesn't get covered.

        Falls back gracefully when the wordmark asset is missing.
        """
        header = QWidget()
        header.setObjectName("brandHeader")
        header.setFixedHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 28, 16, 0)
        layout.setSpacing(10)

        self._brand_glyph = QLabel()
        self._brand_glyph.setFixedSize(24, 24)
        self._refresh_brand_glyph()
        layout.addWidget(self._brand_glyph)

        wordmark = QLabel("Murmur")
        wordmark.setObjectName("brandText")
        layout.addWidget(wordmark)
        layout.addStretch(1)
        return header

    def _refresh_brand_glyph(self) -> None:
        """Pick the wordmark variant that contrasts with the active
        palette: dark glyph for LIGHT, light glyph for DARK.

        Re-runnable so :meth:`set_theme` can flip the asset alongside
        the stylesheet.
        """
        if not hasattr(self, "_brand_glyph"):
            return
        path = (
            _WORDMARK_DARK_PATH
            if self._active_palette is LIGHT
            else _WORDMARK_LIGHT_PATH
        )
        if not path.exists():
            return
        pixmap = QPixmap(str(path)).scaled(
            24, 24,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._brand_glyph.setPixmap(pixmap)

    def _build_bottom_rail_section(self) -> QWidget:
        """About row flush at the bottom of the left rail.

        The previous version mixed in a theme toggle above About; that
        landed in Home → Preferences instead (it's a preference, not
        chrome — see ``HomePage._build_preferences_card``).

        About lives in its own QListWidget so it inherits the same
        selected-row styling as the top nav. We connect its selection
        to the unified nav slot so picking About clears the top-nav
        highlight and the stack flips to page 3.
        """
        self._nav_bottom = QListWidget()
        self._nav_bottom.setObjectName("nav")
        self._nav_bottom.addItem(QListWidgetItem("About"))
        # No "current row" until the user clicks About — we keep the
        # selection clear so picking About is a deliberate jump.
        self._nav_bottom.setCurrentRow(-1)
        # One-row height: bumped to 56 so the item's vertical padding
        # has breathing room and "About" doesn't read as clipped at
        # the bottom of the row. Coupled with the rail's bottom
        # margin, the row sits clearly above the window edge.
        self._nav_bottom.setFixedHeight(56)
        # No scrollbar, no frame — it's a single decorative row.
        self._nav_bottom.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self._nav_bottom.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self._nav_bottom.setFrameShape(QListWidget.Shape.NoFrame)
        self._nav_bottom.itemSelectionChanged.connect(
            self._on_bottom_nav_changed,
        )
        return self._nav_bottom

    # ----- Navigation coordination ----------------------------------------

    def _on_top_nav_changed(self, row: int) -> None:
        """Top-nav row changed — switch the stack and clear the bottom
        nav's selection so we never highlight two destinations at once."""
        if row < 0:
            return
        self._stack.setCurrentIndex(row)
        if self._nav_bottom.currentRow() != -1:
            self._nav_bottom.blockSignals(True)
            self._nav_bottom.setCurrentRow(-1)
            self._nav_bottom.blockSignals(False)

    def _on_bottom_nav_changed(self) -> None:
        """About selected — page index 3. Clears the top-nav highlight."""
        if self._nav_bottom.currentRow() < 0:
            return
        # About is the 4th page (index 3).
        self._stack.setCurrentIndex(3)
        self._nav_top.blockSignals(True)
        self._nav_top.setCurrentRow(-1)
        self._nav_top.blockSignals(False)

    # ----- Theme handling -------------------------------------------------

    def set_theme(self, want_dark: bool) -> None:
        """Apply LIGHT or DARK at runtime.

        Re-applies the global stylesheet via :func:`apply_theme` so every
        widget picks up the new palette without having to be reconstructed.
        Also flips the brand-glyph wordmark asset to the variant that
        contrasts with the new palette."""
        new_palette = DARK if want_dark else LIGHT
        if new_palette is self._active_palette:
            return
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, new_palette)
        self._active_palette = new_palette
        self._refresh_brand_glyph()

    # ----- macOS title bar ------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if not self._titlebar_styled:
            self._configure_macos_titlebar()
            self._titlebar_styled = True

    def _configure_macos_titlebar(self) -> None:
        """Hide the macOS title bar so content extends to the very top of
        the window. Traffic-light buttons stay (the user can still close
        / minimize / maximize). The 28 px top padding in the brand
        header reserves space so the icon + wordmark sit below the
        traffic-light overlay area.

        No-ops on non-macOS platforms and silently degrades if pyobjc
        isn't installed — falling back to the default title bar in that
        case is preferable to crashing on start.

        Also bails out under any non-cocoa Qt platform (offscreen,
        minimal, etc.) — winId() there returns a non-NSView pointer
        and dereferencing it segfaults the test runner. The HUD has the
        same guard for the same reason.
        """
        if sys.platform != "darwin":
            return
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() != "cocoa":
            return
        try:
            import objc
            from AppKit import NSWindowStyleMaskFullSizeContentView
        except ImportError:
            _log.info("pyobjc not available; keeping default title bar")
            return
        view_ptr = int(self.winId())
        if not view_ptr:
            return
        try:
            view = objc.objc_object(c_void_p=view_ptr)
            window = view.window()
            if window is None:
                return
            window.setTitlebarAppearsTransparent_(True)
            # NSWindowTitleHidden = 1
            window.setTitleVisibility_(1)
            window.setStyleMask_(
                window.styleMask() | NSWindowStyleMaskFullSizeContentView,
            )
            # Without an explicit title bar, the user has to be able to
            # drag the window from somewhere — empty rail areas, the
            # brand header, etc. ``setMovableByWindowBackground:`` lets
            # the user click-and-drag any non-interactive surface to
            # move the window.
            window.setMovableByWindowBackground_(True)
        except Exception as e:  # noqa: BLE001
            _log.warning("could not configure macOS title bar: %s", e)

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
