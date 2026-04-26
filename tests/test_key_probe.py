"""KeyProbe widget: synthesize key events, verify the diagnostic display."""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from murmur.key_probe import KeyProbe  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication(sys.argv)


_VK_RIGHT_ALT = 0x3D
_VK_FN = 0x3F
_VK_F9 = 0x65
_VK_LETTER_A = 0x00


def _press(widget: KeyProbe, vk: int, text: str = "") -> None:
    ev = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_unknown,
        Qt.KeyboardModifier.NoModifier,
        0,
        vk,
        0,
        text,
    )
    widget.keyPressEvent(ev)


def test_initial_state_shows_placeholder(qapp):
    probe = KeyProbe()
    assert probe.display_text == KeyProbe.PLACEHOLDER
    assert probe.spec_text == ""
    assert probe.kind_text == ""


def test_modifier_press_reports_modifier(qapp):
    probe = KeyProbe()
    _press(probe, _VK_RIGHT_ALT)
    assert probe.display_text == "Right Option"
    assert probe.spec_text == "<right_alt>"
    assert "Modifier" in probe.kind_text


def test_fn_reports_modifier(qapp):
    probe = KeyProbe()
    _press(probe, _VK_FN)
    assert probe.spec_text == "<fn>"
    assert "Modifier" in probe.kind_text


def test_function_key_reports_regular(qapp):
    probe = KeyProbe()
    _press(probe, _VK_F9)
    assert probe.display_text == "F9"
    assert probe.spec_text == "<f9>"
    assert "Regular" in probe.kind_text


def test_letter_reports_regular(qapp):
    probe = KeyProbe()
    _press(probe, _VK_LETTER_A)
    assert probe.spec_text == "a"
    assert "Regular" in probe.kind_text


def test_unrecognized_key_shows_hint(qapp):
    probe = KeyProbe()
    _press(probe, vk=0xFFFF)  # bogus VK, no text
    assert probe.display_text == KeyProbe.UNRECOGNIZED
    assert probe.spec_text == ""


def test_reset_returns_to_placeholder(qapp):
    probe = KeyProbe()
    _press(probe, _VK_RIGHT_ALT)
    probe.reset()
    assert probe.display_text == KeyProbe.PLACEHOLDER
    assert probe.spec_text == ""
    assert probe.kind_text == ""
