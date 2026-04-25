"""Floating recording HUD — small pill at top of screen while you talk.

Shown only during the RECORDING state so you can see at a glance that Murmur
is listening. Frameless, always-on-top, no Dock entry, click-through-ish
(we don't accept focus, so it doesn't steal the active app).
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget


class RecordingHUD(QWidget):
    WIDTH = 200
    HEIGHT = 48
    TOP_MARGIN = 36

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
        self.resize(self.WIDTH, self.HEIGHT)

        self._t0: float = 0.0
        self._pulse_phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._pulse_phase = (self._pulse_phase + 1) % 20
        self.update()

    def show_at_top_center(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.show()
            return
        geo = screen.availableGeometry()
        x = geo.center().x() - self.WIDTH // 2
        y = geo.top() + self.TOP_MARGIN
        self.move(x, y)
        self._t0 = time.monotonic()
        self._pulse_phase = 0
        self._timer.start()
        self.show()
        self.raise_()

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
