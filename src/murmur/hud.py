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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from ._logging import get_logger

_log = get_logger("hud")


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
    WIDTH = 200
    HEIGHT = 48
    # Vertical gap above the screen's bottom edge. Big enough to clear the
    # Dock when it's pinned to the bottom, small enough to read as "near the
    # bottom" rather than "floating in the middle".
    BOTTOM_MARGIN = 96

    def __init__(self) -> None:
        super().__init__()
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
        self._pulse_phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._pulse_phase = (self._pulse_phase + 1) % 20
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
        self._pulse_phase = 0
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

        # Dark rounded background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 18, 22, 235))
        p.drawRoundedRect(self.rect(), 22, 22)

        # Pulsing red dot — phase ramps 0..19, fold to 0..10..0 for ping-pong
        ramp = self._pulse_phase if self._pulse_phase < 10 else (20 - self._pulse_phase)
        intensity = 0.55 + 0.45 * (ramp / 10)
        dot = QColor(229, 57, 53, int(255 * intensity))
        p.setBrush(dot)
        p.drawEllipse(16, self.HEIGHT // 2 - 7, 14, 14)

        # Label + elapsed time
        p.setPen(QColor(245, 245, 245, 235))
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        p.setFont(font)
        elapsed = max(0.0, time.monotonic() - self._t0)
        text = f"Recording  {elapsed:0.1f}s"
        p.drawText(
            self.rect().adjusted(40, 0, -12, 0),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            text,
        )
        p.end()
