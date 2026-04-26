"""Live "test any key" probe for the Shortcuts page.

Users frequently can't tell whether a particular physical key is
bindable as a hotkey — modifiers, the Fn key, function-row extras and
non-US layouts all behave differently. The probe lets them click into
a focus area and press any key to see exactly what the recorder would
capture: the pynput spec token, a humanized label, and whether it
behaves as a modifier (held alone) or a regular key (combo trigger).

This widget never mutates config; it's purely diagnostic.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .hotkey_recorder import humanize, resolve_key_event


class KeyProbe(QWidget):
    """Focus this widget and press a key to see how Murmur identifies it."""

    PLACEHOLDER = "Click here, then press any key…"
    UNRECOGNIZED = (
        "That key isn't recognized — try a different one, or it may be "
        "intercepted by macOS."
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._target = QLabel(self.PLACEHOLDER)
        self._target.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._target.setMinimumHeight(56)
        self._target.setStyleSheet(
            "padding: 12px; border: 1px dashed #888; border-radius: 6px;"
            "background: palette(base); font-size: 13px;"
        )
        outer.addWidget(self._target)

        details = QHBoxLayout()
        details.setSpacing(12)
        self._spec_label = QLabel("")
        self._spec_label.setStyleSheet(
            "font-family: monospace; color: palette(mid); font-size: 11px;"
        )
        self._kind_label = QLabel("")
        self._kind_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        details.addWidget(self._spec_label, 1)
        details.addWidget(self._kind_label)
        outer.addLayout(details)

    # ----- public API for tests/dialog --------------------------------

    @property
    def display_text(self) -> str:
        return self._target.text()

    @property
    def spec_text(self) -> str:
        return self._spec_label.text()

    @property
    def kind_text(self) -> str:
        return self._kind_label.text()

    def reset(self) -> None:
        self._target.setText(self.PLACEHOLDER)
        self._spec_label.setText("")
        self._kind_label.setText("")

    # ----- Qt key handling --------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.isAutoRepeat():
            return
        mapped = resolve_key_event(event)
        if mapped is None:
            self._target.setText(self.UNRECOGNIZED)
            self._spec_label.setText("")
            self._kind_label.setText("")
            return
        token, is_modifier = mapped
        self._target.setText(humanize(token))
        self._spec_label.setText(token)
        self._kind_label.setText(
            "Modifier (works alone)" if is_modifier else "Regular key (use in combo)"
        )
