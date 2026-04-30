"""Floating recording HUD — small pill near the bottom of the screen while you talk.

Shown only during the RECORDING state so you can see at a glance that Murmur
is listening. Frameless, always-on-top, no Dock entry, and — critically —
non-activating: the underlying NSPanel never becomes key, so showing it
doesn't steal focus from whatever text field the user is typing into.
Without this, push-to-talk would yank focus on every recording, leaving
auto-paste with no cursor to paste at.

The HUD lives near the bottom of the primary screen. The macOS menu bar
on top tends to compete visually with the indicator there, and bottom
placement is closer to where the cursor / dock activity already is.
"""
from __future__ import annotations

import platform
import time
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from ._logging import get_logger

_log = get_logger("hud")


def _format_elapsed(seconds: float) -> str:
    """Adaptive elapsed-time format — truncates rather than rounds.

    Under one minute the readout shows decimal seconds (e.g. ``12.3s``) so
    short utterances feel responsive. At and beyond 60.0s the format flips
    to whole-second ``Nm Ms`` so the pill stays narrow on long takes.

    The 60.0s flip is exact — 59.999... still renders as ``59.9s`` because
    we truncate the tenths digit, while 60.0 prints as ``1m 0s``.
    """
    if seconds < 0:
        seconds = 0.0
    if seconds < 60.0:
        # Truncate to one decimal place: floor(seconds * 10) / 10.
        tenths = int(seconds * 10)
        whole = tenths // 10
        frac = tenths % 10
        return f"{whole}.{frac}s"
    total_whole = int(seconds)  # floor for non-negative floats
    minutes = total_whole // 60
    secs = total_whole % 60
    return f"{minutes}m {secs}s"


def _apply_nonactivating_panel_style(widget: QWidget) -> None:
    """Make the widget's NSPanel a true status-bar-style overlay.

    Wispr-Flow-style: the pill is purely visual — it never becomes key,
    never absorbs clicks/keystrokes, follows the user across Spaces, and
    sits above ordinary windows. Reapplied on every show() because Qt
    can re-init window properties after hide()/show() cycles.

    Each piece earns its place:
    - NSWindowStyleMaskNonactivatingPanel: AppKit refuses to make this
      panel key, so [NSApp keyWindow] stays on the user's text field.
    - NSStatusWindowLevel: above normal windows but below the menu bar's
      true status items, matching what dictation HUDs use.
    - canJoinAllSpaces|stationary|ignoresCycle|transient: the panel
      doesn't follow Cmd-Tab cycling and doesn't pull the app forward
      when a Space change happens.
    - hidesOnDeactivate=False: keep the indicator visible while the
      user types into another app.
    - ignoresMouseEvents=True: clicks pass straight through to whatever
      is underneath; the HUD is purely informational.
    """
    if platform.system() != "Darwin":
        return
    # Only the real Cocoa QPA backs Qt windows with NSView/NSWindow. Under
    # the offscreen platform used in tests, winId() returns a non-NSView
    # pointer and dereferencing it via objc segfaults.
    if QGuiApplication.platformName() != "cocoa":
        return
    try:
        import objc
        from AppKit import (
            NSStatusWindowLevel,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorIgnoresCycle,
            NSWindowCollectionBehaviorStationary,
            NSWindowCollectionBehaviorTransient,
            NSWindowStyleMaskNonactivatingPanel,
        )
    except ImportError:
        _log.warning("pyobjc unavailable; HUD may steal focus on macOS")
        return

    view_ptr = int(widget.winId())
    if not view_ptr:
        return
    try:
        view = objc.objc_object(c_void_p=view_ptr)
        window = view.window()
        if window is None:
            return
        window.setStyleMask_(window.styleMask() | NSWindowStyleMaskNonactivatingPanel)
        window.setLevel_(NSStatusWindowLevel)
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle
            | NSWindowCollectionBehaviorTransient
        )
        window.setHidesOnDeactivate_(False)
        window.setIgnoresMouseEvents_(True)
    except Exception as e:  # noqa: BLE001
        _log.warning("could not configure HUD panel: %s", e)


class RecordingHUD(QWidget):
    # Compact pill — half the previous 200x48 footprint so it competes
    # less with whatever the user is reading while they dictate.
    WIDTH = 100
    HEIGHT = 24
    # Vertical gap above the screen's bottom edge. Big enough to clear the
    # Dock when it's pinned to the bottom, small enough to read as "near the
    # bottom" rather than "floating in the middle".
    BOTTOM_MARGIN = 96

    # Visual contract for the three dots in the left cluster.
    #
    # Static baseline (silent / no level provider): 2 px diameter, ~30 % alpha.
    # When the level rises toward 1.0 the diameter grows to 6 px and the
    # alpha climbs to 255 — see ``_dot_geometry_for_level`` for the exact
    # mapping. The baseline numbers are kept here so the silent-mode
    # rendering remains a regression pin against #14.
    _DOT_BASELINE_DIAMETER = 2
    _DOT_PEAK_DIAMETER = 6
    _DOT_BASELINE_ALPHA = 77  # ~30 % of 255
    _DOT_PEAK_ALPHA = 255
    _DOT_COUNT = 3
    _DOT_CLUSTER_LEFT = 8  # px from left edge of pill to first dot's center column
    _DOT_CLUSTER_WIDTH = 22  # leaves the cluster occupying the left ~30px
    _DOT_RGB = (245, 245, 245)  # neutral light gray; alpha is dynamic

    def __init__(
        self,
        level_provider: Callable[[], float] | None = None,
    ) -> None:
        """Construct the HUD.

        ``level_provider`` is an optional zero-arg callable returning the
        current mic volume in [0.0, 1.0]. We accept a callable rather than a
        ``Recorder`` reference so the HUD stays decoupled from ``audio.py``
        — tests just pass ``lambda: 0.5`` and the production wiring passes
        ``lambda: recorder.current_level``. If ``None`` (or the callable
        raises), the dots fall back to the static baseline.
        """
        super().__init__()
        self._level_provider = level_provider
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # no Dock / app-switcher entry on macOS
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Belt-and-suspenders click-through: even if the AppKit-level
        # ignoresMouseEvents call fails to land for some reason, Qt itself
        # won't try to consume mouse input on this widget.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(self.WIDTH, self.HEIGHT)

        self._t0: float = 0.0
        # Timer drives repaint() so both the elapsed-time text and the
        # volume-reactive dots stay current. 33 ms (~30 Hz) is smooth enough
        # that the dots don't strobe on speech transients; the repaint cost
        # is one rect + three small ellipses + a short string, so the bump
        # from 80 ms is essentially free.
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def set_level_provider(
        self, provider: Callable[[], float] | None
    ) -> None:
        """Late-bind the level source. Useful when the HUD is constructed
        before the recorder is available (or vice versa)."""
        self._level_provider = provider

    def _current_level(self) -> float:
        """Read the level provider defensively. Never raises — a broken
        provider degrades to the static baseline rather than crashing the
        HUD repaint."""
        if self._level_provider is None:
            return 0.0
        try:
            level = float(self._level_provider())
        except Exception:  # noqa: BLE001
            return 0.0
        if level < 0.0:
            return 0.0
        if level > 1.0:
            return 1.0
        return level

    def _tick(self) -> None:
        # Just nudge a repaint — only the timer text needs refreshing now.
        self.update()

    def show_at_bottom_center(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.show()
            return
        geo = screen.availableGeometry()
        x = geo.center().x() - self.WIDTH // 2
        y = geo.bottom() - self.HEIGHT - self.BOTTOM_MARGIN
        self.move(x, y)
        self._t0 = time.monotonic()
        self._timer.start()
        self.show()
        # Reapply on every show: Qt may regenerate the underlying NSPanel
        # after a hide()/show() cycle, which resets the style mask, level,
        # and collection behavior we set last time.
        _apply_nonactivating_panel_style(self)

    def hide(self) -> None:
        self._timer.stop()
        super().hide()

    def paintEvent(self, _e) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dark rounded background — 12px radius is proportional to the
        # 22px we used at the previous 2x size.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 18, 22, 235))
        p.drawRoundedRect(self.rect(), 12, 12)

        # Three dots in the left cluster, driven by live mic volume.
        # At level=0 they match #14's static baseline (2 px, ~30 % alpha);
        # any sound expands and brightens them linearly up to (6 px, 100 %)
        # at level=1. No VAD threshold — silence is just zero level.
        level = self._current_level()
        # radius = 1 + 2 * level → diameter 2..6 px as level 0..1
        radius_px = 1.0 + 2.0 * level
        diameter_px = int(round(2.0 * radius_px))
        alpha = self._DOT_BASELINE_ALPHA + int(round(
            (self._DOT_PEAK_ALPHA - self._DOT_BASELINE_ALPHA) * level
        ))
        r, g, b = self._DOT_RGB
        p.setBrush(QColor(r, g, b, alpha))
        # Evenly space N dots across the cluster band: positions land at
        # i / (N - 1) of the band's interior. The cluster's center column
        # is anchor-stable as the dots breathe — we draw each ellipse
        # centered on (anchor_x, anchor_y) so growth radiates from the dot's
        # midpoint rather than its top-left corner.
        anchor_y = self.HEIGHT // 2
        step = (
            self._DOT_CLUSTER_WIDTH / (self._DOT_COUNT - 1)
            if self._DOT_COUNT > 1
            else 0
        )
        # Anchor each baseline dot at the same x as before by shifting the
        # cluster origin half a baseline-diameter to the right.
        anchor_left = self._DOT_CLUSTER_LEFT + self._DOT_BASELINE_DIAMETER // 2
        for i in range(self._DOT_COUNT):
            anchor_x = anchor_left + int(round(i * step))
            top_left_x = anchor_x - diameter_px // 2
            top_left_y = anchor_y - diameter_px // 2
            p.drawEllipse(top_left_x, top_left_y, diameter_px, diameter_px)

        # Elapsed-time readout — adaptive format keeps the pill narrow.
        p.setPen(QColor(245, 245, 245, 235))
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        p.setFont(font)
        elapsed = max(0.0, time.monotonic() - self._t0)
        text = _format_elapsed(elapsed)
        # Reserve the left cluster for dots, right edge gets a small inset
        # so the text doesn't crowd the pill's rounded corner.
        text_left = self._DOT_CLUSTER_LEFT + self._DOT_CLUSTER_WIDTH + 6
        p.drawText(
            self.rect().adjusted(text_left, 0, -8, 0),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            text,
        )
        p.end()
