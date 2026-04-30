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
    QPushButton,
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


def _palette_rail_rgb(palette) -> tuple[float, float, float]:
    """Decode the active palette's ``rail_bg`` hex into 0–1 RGB floats.

    Used to match NSWindow's background to the rail so the title-bar
    zone blends with the window chrome instead of showing as a gray
    strip. Falls back to the LIGHT palette's cream if anything looks
    malformed — better a slight color mismatch than a crash on a
    user-themed build.
    """
    hex_str = (palette.rail_bg or "#f1ebe2").lstrip("#")
    if len(hex_str) != 6:
        hex_str = "f1ebe2"
    r = int(hex_str[0:2], 16) / 255.0
    g = int(hex_str[2:4], 16) / 255.0
    b = int(hex_str[4:6], 16) / 255.0
    return r, g, b


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

        # Theme state mirrors what the persisted Config says. The
        # caller (tray.py) has already applied the matching palette
        # globally before constructing the window.
        self._active_palette = DARK if cfg.dark_mode else LIGHT

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
        # Bottom margin: 32 px so the About row sits well clear of the
        # window's rounded bottom corner. 24 still rendered as clipped
        # against the bezel on the user's display.
        rail_layout.setContentsMargins(0, 0, 0, 32)
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

        # Window dragging is now handled natively by AppKit — the
        # standard title bar is back (just styled to blend with the
        # rail). No Qt-side drag plumbing needed.

    # ----- Construction helpers -------------------------------------------

    def _build_brand_header(self) -> QWidget:
        """Top-of-rail brand bar + drag region for the frameless window.

        Three earlier dragging implementations all failed in the
        bundled .app — ``startSystemMove()``, ``[NSWindow
        performWindowDragWithEvent:]``, and per-widget mouse handlers
        on a ``_DragHeader`` subclass. The first two no-op'd
        silently; the third was either not receiving the press at all
        or ``QWidget.move()`` was being snapped back by AppKit.

        The approach that *does* work is a global event filter on
        ``QApplication`` (see ``MainWindow.eventFilter``). It runs
        before any widget-level handlers, so it doesn't matter if a
        child widget would otherwise eat the press. The filter
        region-checks the press against the brand header's rect and
        manages the drag offset itself.

        So this method just builds the visible chrome. The header's
        own mouse handlers are never used.
        """
        header = QWidget(self)
        header.setObjectName("brandHeader")
        header.setFixedHeight(48)
        # No 28-px top padding any more: with the standard title bar
        # back, traffic lights live in their own strip above the
        # brand header. The header just needs comfortable side and
        # vertical breathing room.
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 12, 16, 0)
        layout.setSpacing(10)

        self._brand_glyph = QLabel()
        self._brand_glyph.setFixedSize(24, 24)
        self._refresh_brand_glyph()
        layout.addWidget(self._brand_glyph)

        wordmark = QLabel("Murmur")
        wordmark.setObjectName("brandText")
        layout.addWidget(wordmark)
        layout.addStretch(1)
        self._brand_header = header
        return header

    def _refresh_brand_glyph(self) -> None:
        """Show the orange app icon next to the 'Murmur' wordmark.

        We tried a theme-aware monochrome silhouette here briefly; the
        maintainer prefers the colorful app icon as the rail mark for
        brand recognition. The silhouette stays in the assets folder
        for the tray to use (see ``tray.py`` — black μ on transparent
        for the menu-bar idle state).
        """
        if not hasattr(self, "_brand_glyph"):
            return
        if not _ICON_PATH.exists():
            return
        pixmap = QPixmap(str(_ICON_PATH)).scaled(
            24, 24,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._brand_glyph.setPixmap(pixmap)

    def _build_bottom_rail_section(self) -> QWidget:
        """About row flush at the bottom of the left rail.

        Earlier versions used a one-item ``QListWidget`` here so the
        About row would inherit the top nav's selection styling. The
        list widget's viewport paints itself with the QPalette
        ``Base`` color, which is *slightly* lighter than the rail's
        ``rail_bg`` — so the row read as a separate floating panel
        sitting on the rail (the user flagged this in #59).

        Replaced it with a styled ``QPushButton``. Clicks toggle to
        the About page; the ``[navItem="true"]`` style property
        gives it the same hover + selected rendering as the top
        nav rows. No QListWidget viewport, no color mismatch.
        """
        host = QWidget()
        host.setObjectName("railBottom")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(0)

        self._about_button = QPushButton("About")
        self._about_button.setObjectName("aboutNav")
        self._about_button.setProperty("navItem", True)
        self._about_button.setCheckable(True)
        self._about_button.setChecked(False)
        self._about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._about_button.clicked.connect(self._on_about_clicked)
        layout.addWidget(self._about_button)

        return host

    # ----- Navigation coordination ----------------------------------------

    def _on_top_nav_changed(self, row: int) -> None:
        """Top-nav row changed — switch the stack and clear the About
        button's checked state so we never highlight two destinations
        at once."""
        if row < 0:
            return
        self._stack.setCurrentIndex(row)
        if self._about_button.isChecked():
            self._about_button.setChecked(False)

    def _on_about_clicked(self) -> None:
        """About button clicked — switch to the About page (index 3)
        and clear the top-nav highlight. The button stays checked
        until another nav destination is picked."""
        self._stack.setCurrentIndex(3)
        self._about_button.setChecked(True)
        self._nav_top.blockSignals(True)
        self._nav_top.setCurrentRow(-1)
        self._nav_top.blockSignals(False)

    # ----- Theme handling -------------------------------------------------

    def set_theme(self, want_dark: bool) -> None:
        """Apply LIGHT or DARK at runtime.

        Re-applies the global stylesheet via :func:`apply_theme` so every
        widget picks up the new palette without having to be reconstructed.
        Also flips the brand-glyph wordmark asset to the variant that
        contrasts with the new palette, and refreshes the NSWindow
        background color so the title-bar zone keeps matching the rail."""
        new_palette = DARK if want_dark else LIGHT
        if new_palette is self._active_palette:
            return
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, new_palette)
        self._active_palette = new_palette
        self._refresh_brand_glyph()
        # Re-tint the NSWindow background so the title-bar zone keeps
        # matching the (now-different) rail color.
        if self._titlebar_styled:
            self._configure_macos_titlebar()

    # ----- macOS title bar ------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        if not self._titlebar_styled:
            self._configure_macos_titlebar()
            self._titlebar_styled = True

    def _configure_macos_titlebar(self) -> None:
        """Style the macOS title bar to blend with the rail.

        Earlier versions used ``NSWindowStyleMaskFullSizeContentView``
        to extend content behind a transparent title bar, plus a
        QApplication-level event filter to make the brand header drag
        the window. After three rebuilds the user reported drag still
        didn't work. ``FullSizeContentView`` + Qt's giant NSView
        appears to interfere with AppKit's hit-testing in ways that
        break both AppKit's native drag *and* Qt's mouse dispatch.

        New approach: leave the standard title bar in place (so AppKit
        drags the window natively) but style it so it doesn't read as
        a foreign element:

        - ``setTitleVisibility:NSWindowTitleHidden`` hides the
          ``"Murmur"`` text the user flagged.
        - ``setTitlebarAppearsTransparent:YES`` removes the title-bar
          chrome line so it reads as one continuous strip with the
          window content.
        - ``setBackgroundColor:`` ties the strip's color to the
          active palette's rail, so the result looks like the rail
          extending up to the traffic lights.

        Bails out cleanly off-cocoa (offscreen tests, non-macOS).
        """
        if sys.platform != "darwin":
            return
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() != "cocoa":
            return
        try:
            import objc
            from AppKit import NSColor
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
            r, g, b = _palette_rail_rgb(self._active_palette)
            window.setBackgroundColor_(
                NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0),
            )
            # Native title-bar drag is back on (we no longer set
            # FullSizeContentView), so AppKit handles window movement
            # without any Qt-side help.
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
