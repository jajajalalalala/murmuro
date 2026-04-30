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
from collections import deque
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
    # Compact pill. The 88 px width is sized to the longest realistic timer
    # ("1m 23s" worst-case for a typical push-to-talk burst) plus the bar
    # cluster, so the content reads close to centered rather than crowded
    # to the left with empty space on the right.
    WIDTH = 88
    HEIGHT = 24
    # Vertical gap above the screen's bottom edge. Big enough to clear the
    # Dock when it's pinned to the bottom, small enough to read as "near the
    # bottom" rather than "floating in the middle".
    BOTTOM_MARGIN = 96

    # Visual contract for the 5-bar staggered waveform in the left cluster.
    #
    # Five vertical bars, 2 px wide with a 3 px gap, vertically centered in
    # the 24 px pill. Each bar reads from its own slot in a 5-element ring
    # buffer of recent levels — the rightmost bar is the newest sample, the
    # leftmost is the oldest (~133 ms back at 30 Hz), so voice peaks visibly
    # travel left-to-right as the user speaks.
    #
    # Geometry: height ramps 2 → 18 px (silent → peak), opacity ramps
    # 127 → 255 (50 % → 100 %). Color is pure white — brighter than the
    # previous (245, 245, 245) so the waveform reads cleanly against the
    # dark pill at every level.
    _BAR_COUNT = 5
    _BAR_WIDTH = 2
    _BAR_GAP = 3
    _BAR_BASELINE_HEIGHT = 2
    _BAR_PEAK_HEIGHT = 18
    _BAR_BASELINE_ALPHA = 127  # 50 % of 255
    _BAR_PEAK_ALPHA = 255
    _BAR_CLUSTER_LEFT = 10  # px from left edge of pill to first bar's left edge
    # 5 bars × 2 px + 4 gaps × 3 px = 22 px total horizontal footprint.
    _BAR_CLUSTER_WIDTH = (
        _BAR_COUNT * _BAR_WIDTH + (_BAR_COUNT - 1) * _BAR_GAP
    )
    _BAR_RGB = (255, 255, 255)  # pure white; alpha is dynamic

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
        raises), the bars fall back to the silent baseline.
        """
        super().__init__()
        self._level_provider = level_provider
        # Ring buffer of recent levels — one slot per bar. Pre-populated
        # with zeros so a freshly-constructed HUD with no ticks yet renders
        # all bars at the silent baseline rather than uninitialised noise.
        # Newest sample is appended to the right; the rightmost bar reads
        # the newest level and the leftmost reads the oldest still in the
        # buffer (~133 ms ago at 30 Hz).
        self._levels: deque[float] = deque(
            [0.0] * self._BAR_COUNT, maxlen=self._BAR_COUNT
        )
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
        # Timer drives the level sample + repaint. 33 ms (~30 Hz) is smooth
        # enough that the bars don't strobe on speech transients; the
        # repaint cost is one rect + five small rects + a short string.
        # The cadence also sets the stagger speed: 5 slots × 33 ms = ~165 ms
        # for a level to traverse from the rightmost bar to the leftmost.
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
        # Sample the level once per tick and push it onto the ring buffer.
        # Doing the sample here (not in paintEvent) means each bar slot
        # corresponds to a distinct point in time even if Qt coalesces
        # repaints — the stagger is driven by the timer, not the painter.
        self._levels.append(self._current_level())
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

        # 5-bar staggered waveform driven by the level ring buffer.
        # Each bar reads its own slot — the rightmost is the newest sample
        # and the leftmost is the oldest still in the buffer. Voice peaks
        # therefore visibly travel left-to-right as the user speaks. At
        # level=0 every bar collapses to the 2 px / 50 % alpha silent
        # baseline; at level=1 it reaches 18 px / 100 %.
        r, g, b = self._BAR_RGB
        center_y = self.HEIGHT // 2
        # Snapshot the deque so concurrent _tick() appends can't shift the
        # mapping mid-paint. deque is index-cheap; the copy is 5 floats.
        slot_levels = list(self._levels)
        for i in range(self._BAR_COUNT):
            slot_level = slot_levels[i]
            # Defensive clamp — _current_level already clamps, but the
            # ring buffer could in principle contain a stale out-of-range
            # value if the contract ever changes.
            if slot_level < 0.0:
                slot_level = 0.0
            elif slot_level > 1.0:
                slot_level = 1.0
            bar_height = self._BAR_BASELINE_HEIGHT + int(
                (self._BAR_PEAK_HEIGHT - self._BAR_BASELINE_HEIGHT) * slot_level
            )
            bar_alpha = self._BAR_BASELINE_ALPHA + int(
                (self._BAR_PEAK_ALPHA - self._BAR_BASELINE_ALPHA) * slot_level
            )
            bar_left = self._BAR_CLUSTER_LEFT + i * (
                self._BAR_WIDTH + self._BAR_GAP
            )
            bar_top = center_y - bar_height // 2
            p.setBrush(QColor(r, g, b, bar_alpha))
            p.drawRect(bar_left, bar_top, self._BAR_WIDTH, bar_height)

        # Elapsed-time readout — adaptive format keeps the pill narrow.
        p.setPen(QColor(245, 245, 245, 235))
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        p.setFont(font)
        elapsed = max(0.0, time.monotonic() - self._t0)
        text = _format_elapsed(elapsed)
        # Reserve the left cluster for bars, right edge gets a small inset
        # so the text doesn't crowd the pill's rounded corner.
        text_left = self._BAR_CLUSTER_LEFT + self._BAR_CLUSTER_WIDTH + 6
        p.drawText(
            self.rect().adjusted(text_left, 0, -8, 0),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            text,
        )
        p.end()
