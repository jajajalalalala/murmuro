"""Custom modal dialogs that match the Murmur main-window styling.

QMessageBox is the path-of-least-resistance for a "tell the user
something + ask them to pick" interaction, but its title bar, icon,
and chrome are macOS-native — clicking through one feels like
ducking out of the app into a generic system dialog.

This module ships a single ``MurmurDialog`` primitive that reuses
the cream-card look + native title-bar styling we apply to the main
window. The accessibility-permission hint is the first caller; the
hotkey-restart modal and the delete-model confirm are obvious
follow-ups.
"""
from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .._logging import get_logger
from .theme import LIGHT, DARK, primary_button

_log = get_logger("ui.dialogs")


@dataclass(frozen=True)
class DialogButton:
    """One button in a :class:`MurmurDialog` footer.

    ``primary`` styles the button with the orange accent — at most
    one button per dialog should be primary. ``role`` mirrors
    ``QDialogButtonBox`` semantics enough for tests/callers to
    introspect.
    """

    text: str
    role: str = "accept"      # "accept" | "reject" | "action"
    primary: bool = False


class MurmurDialog(QDialog):
    """Modal dialog styled to match the Murmur main window.

    Layout: a single cream surface (rail-color background) with a
    bold title, a body paragraph, an optional list of step lines,
    and a footer button row (secondary on the left, primary on the
    right). The macOS title bar uses the same transparent + hidden-
    title treatment as the main window so the popup reads as part
    of Murmur rather than a system alert.

    Construction is declarative — callers pass title, body, optional
    steps, and a list of :class:`DialogButton`. The clicked button's
    text is stashed on ``clicked_text`` after ``exec()`` returns so
    callers can branch on which one the user picked.
    """

    def __init__(
        self,
        *,
        title: str,
        body: str,
        steps: Sequence[str] = (),
        buttons: Sequence[DialogButton],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        # Modal — block the rest of the app until dismissed.
        self.setModal(True)
        # Slightly wider than the default QDialog so the body and
        # steps don't wrap awkwardly. Tall enough for a long body
        # plus three step lines without a scrollbar.
        self.setMinimumWidth(520)

        self.clicked_text: str | None = None
        self._buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title_label)

        body_label = QLabel(body)
        body_label.setWordWrap(True)
        layout.addWidget(body_label)

        if steps:
            steps_box = QVBoxLayout()
            steps_box.setContentsMargins(0, 4, 0, 0)
            steps_box.setSpacing(4)
            for i, step in enumerate(steps, start=1):
                line = QLabel(f"{i}. {step}")
                line.setWordWrap(True)
                line.setProperty("dim", True)
                steps_box.addWidget(line)
            layout.addLayout(steps_box)

        layout.addStretch(1)

        # Footer: stretch on the left pushes everything to the right
        # so the primary action lands in the bottom-right corner —
        # the spot users' eyes go to in a Mac-style sheet.
        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch(1)
        for spec in buttons:
            btn = primary_button(spec.text) if spec.primary else QPushButton(spec.text)
            btn.clicked.connect(self._on_clicked(spec))
            if spec.role == "accept" and spec.primary:
                btn.setDefault(True)
            self._buttons[spec.text] = btn
            footer.addWidget(btn)
        layout.addLayout(footer)

        self._apply_native_titlebar()

    def _on_clicked(self, spec: DialogButton) -> Callable[[], None]:
        def handler() -> None:
            self.clicked_text = spec.text
            if spec.role == "reject":
                self.reject()
            else:
                self.accept()
        return handler

    # ----- macOS title bar styling --------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        self._apply_native_titlebar()

    def _apply_native_titlebar(self) -> None:
        """Tint the NSWindow title bar to match the main window.

        Same trick as ``MainWindow._configure_macos_titlebar``:
        transparent title bar, hidden title text, NSWindow
        backgroundColor matched to the active palette's rail. Falls
        back silently on non-macOS / offscreen test runs.
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
            window.setTitleVisibility_(1)  # NSWindowTitleHidden
            r, g, b = _active_rail_rgb()
            window.setBackgroundColor_(
                NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0),
            )
        except Exception as e:  # noqa: BLE001
            _log.warning("could not configure dialog title bar: %s", e)


def _active_rail_rgb() -> tuple[float, float, float]:
    """Inspect the QApplication palette to pick the right rail color.

    The dialog can't import MainWindow's own RGB helper without
    creating a circular dependency, so we re-derive it from the
    active palette here. The DARK palette's rail_bg is darker than
    a Window lightness of 80 — that's our cheap dark/light test.
    """
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        palette = LIGHT
    else:
        win_color = app.palette().color(QPalette.ColorRole.Window)
        palette = DARK if win_color.lightness() < 80 else LIGHT
    hex_str = (palette.rail_bg or "#f1ebe2").lstrip("#")
    r = int(hex_str[0:2], 16) / 255.0
    g = int(hex_str[2:4], 16) / 255.0
    b = int(hex_str[4:6], 16) / 255.0
    return r, g, b


__all__ = ["DialogButton", "MurmurDialog"]
