"""Custom widgets used across pages.

So far: a single ``ToggleSwitch`` — an iOS/macOS-style sliding-knob
toggle — and a ``preference_row`` helper that pairs a title + optional
caption with a switch on the right. We use these in place of plain
``QCheckBox`` for Home → Preferences because the user feedback was
that the bare checkboxes felt office-software-y; a label-left,
switch-right row reads like a modern preferences sheet.

``ToggleSwitch`` deliberately subclasses ``QAbstractButton`` so it
inherits ``setChecked()`` / ``isChecked()`` / ``toggled`` — drop-in
compatible with any code that previously held ``QCheckBox``.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import ACCENT


class ToggleSwitch(QAbstractButton):
    """Sliding-knob toggle. Drop-in for QCheckBox where the on/off
    affordance matters more than the label association.

    Track interpolates between an off color (theme-muted gray) and the
    accent color when checked. The knob slides via
    ``QPropertyAnimation`` so toggling feels intentional, not a
    rectangle blink.
    """

    _TRACK_W = 40
    _TRACK_H = 22
    _MARGIN = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(self._TRACK_W, self._TRACK_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 0.0 = off (knob fully left), 1.0 = on (knob fully right).
        self._knob_pos: float = 0.0
        # Animation that drives _knob_pos as state flips.
        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_to_state)

    # --- Animatable Qt property -------------------------------------------

    def _get_knob_pos(self) -> float:
        return self._knob_pos

    def _set_knob_pos(self, value: float) -> None:
        self._knob_pos = max(0.0, min(1.0, float(value)))
        self.update()

    knobPos = Property(float, _get_knob_pos, _set_knob_pos)  # noqa: N815

    # --- Behavior ----------------------------------------------------------

    def _animate_to_state(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._knob_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (Qt API)
        # When checked is set programmatically (not by the user clicking),
        # snap the knob to the right position so it doesn't visibly jump.
        super().setChecked(checked)
        self._knob_pos = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Track — interpolate between off (palette mid gray) and accent.
        pal = self.palette()
        off_color = pal.color(self.palette().ColorRole.Mid)
        on_color = QColor(ACCENT)
        t = self._knob_pos
        track = QColor(
            int(off_color.red() * (1 - t) + on_color.red() * t),
            int(off_color.green() * (1 - t) + on_color.green() * t),
            int(off_color.blue() * (1 - t) + on_color.blue() * t),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        radius = self.height() / 2
        p.drawRoundedRect(self.rect(), radius, radius)

        # Knob — pure white circle that slides between margins.
        diameter = self.height() - 2 * self._MARGIN
        x_min = self._MARGIN
        x_max = self.width() - diameter - self._MARGIN
        x = x_min + (x_max - x_min) * t
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(x, self._MARGIN, diameter, diameter))


def preference_row(
    title: str,
    *,
    caption: str | None = None,
    initial: bool = False,
    on_toggled: Callable[[bool], None] | None = None,
) -> tuple[QWidget, ToggleSwitch]:
    """A label-on-left + ToggleSwitch-on-right row, with optional dim
    caption underneath the title.

    Returns ``(row_widget, switch)`` so callers can wire signals on the
    switch and add ``row_widget`` to their layout. Pulled into a helper
    so the Home page's three+ preferences read as identical structure
    rather than ad-hoc constructions.
    """
    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(12)

    text_col = QVBoxLayout()
    text_col.setContentsMargins(0, 0, 0, 0)
    text_col.setSpacing(2)
    title_label = QLabel(title)
    title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    text_col.addWidget(title_label)
    if caption:
        cap = QLabel(caption)
        cap.setProperty("dim", True)
        cap.setWordWrap(True)
        text_col.addWidget(cap)
    row_layout.addLayout(text_col, 1)

    switch = ToggleSwitch()
    switch.setChecked(initial)
    if on_toggled is not None:
        switch.toggled.connect(on_toggled)
    row_layout.addWidget(switch, 0, Qt.AlignmentFlag.AlignTop)
    return row, switch
