"""HotkeyRecorder: simulate Qt key events, verify the captured pynput spec."""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from murmur.hotkey_recorder import HotkeyRecorder, humanize  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication(sys.argv)


# macOS virtual keycodes used in the recorder's mapping table.
_VK_RIGHT_ALT = 0x3D
_VK_LEFT_CTRL = 0x3B
_VK_LEFT_SHIFT = 0x38
_VK_SPACE = 0x31
_VK_F9 = 0x65
_VK_F17 = 0x40
_VK_CAPS_LOCK = 0x39
_VK_LEFT_ARROW = 0x7B
_VK_PAGE_UP = 0x74
_VK_KP_5 = 0x57
_VK_DIGIT_5 = 0x17  # top-row 5
_VK_LETTER_A = 0x00
_VK_SEMICOLON = 0x29


def _press(widget: HotkeyRecorder, vk: int, text: str = "") -> None:
    """Synthesize a keyPressEvent with the given native virtual keycode."""
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


def _release(widget: HotkeyRecorder, vk: int, text: str = "") -> None:
    ev = QKeyEvent(
        QKeyEvent.Type.KeyRelease,
        Qt.Key.Key_unknown,
        Qt.KeyboardModifier.NoModifier,
        0,
        vk,
        0,
        text,
    )
    widget.keyReleaseEvent(ev)


def test_modifier_only_hotkey_committed_on_release(qapp):
    """Press Right Option, release it → '<right_alt>' captured."""
    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_RIGHT_ALT)
    assert rec._recording  # not yet committed; user still holding
    _release(rec, _VK_RIGHT_ALT)
    assert rec.value() == "<right_alt>"
    assert not rec._recording


def test_combo_with_non_modifier_committed_on_press(qapp):
    """Ctrl+Shift+Space → committed as soon as Space goes down."""
    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_LEFT_CTRL)
    _press(rec, _VK_LEFT_SHIFT)
    _press(rec, _VK_SPACE)
    assert rec.value() == "<left_ctrl>+<left_shift>+<space>"
    assert not rec._recording


def test_function_key_alone(qapp):
    """F9 alone → '<f9>' (non-modifier commits on press)."""
    rec = HotkeyRecorder("<right_alt>")
    rec._start_recording()
    _press(rec, _VK_F9)
    assert rec.value() == "<f9>"


def test_letter_key_with_modifier(qapp):
    """Ctrl + A — letter detected via event.text(), not VK table."""
    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_LEFT_CTRL)
    _press(rec, vk=0, text="a")  # vk=0 forces fall-through to text()
    assert rec.value() == "<left_ctrl>+a"


def test_escape_cancels_recording(qapp):
    """Esc with nothing held → exit record mode without changing value."""
    rec = HotkeyRecorder("<right_alt>")
    rec._start_recording()
    ev = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )
    rec.keyPressEvent(ev)
    assert rec.value() == "<right_alt>"
    assert not rec._recording


def test_humanize_modifier(qapp):
    assert humanize("<right_alt>") == "Right Option"
    assert humanize("<f9>") == "F9"
    assert humanize("<ctrl>+<shift>+<space>") == "Ctrl + Shift + Space"
    assert humanize("a") == "A"
    assert humanize("") == "(none)"
    assert humanize("<caps_lock>") == "Caps Lock"
    assert humanize("<page_up>") == "Page Up"
    assert humanize("<left>") == "←"
    assert humanize("<f17>") == "F17"


def test_top_row_digit_records_unshifted_via_vk(qapp):
    """Shift+5 should commit as '<left_shift>+5', not '%'."""
    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_LEFT_SHIFT)
    # Qt would deliver text="%" for shifted 5 — the recorder must ignore
    # event.text() and use the VK to recover the physical key.
    _press(rec, _VK_DIGIT_5, text="%")
    assert rec.value() == "<left_shift>+5"


def test_letter_via_vk_table(qapp):
    """Letter resolved by VK even with no event.text()."""
    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_LETTER_A)
    assert rec.value() == "a"


def test_punctuation_via_vk_unshifted(qapp):
    """Shift+; should commit as '<left_shift>+;', not ':'."""
    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_LEFT_SHIFT)
    _press(rec, _VK_SEMICOLON, text=":")
    assert rec.value() == "<left_shift>+;"


def test_caps_lock_recorded_as_modifier(qapp):
    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_CAPS_LOCK)
    _release(rec, _VK_CAPS_LOCK)
    assert rec.value() == "<caps_lock>"


def test_navigation_cluster_keys(qapp):
    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_PAGE_UP)
    assert rec.value() == "<page_up>"

    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_LEFT_ARROW)
    assert rec.value() == "<left>"


def test_keypad_digit_collapses_to_top_row_glyph(qapp):
    """Keypad keys share a spec with their top-row equivalents so pynput
    (which has no keypad enum on macOS) can still bind the resulting
    hotkey."""
    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_KP_5)
    assert rec.value() == "5"


def test_extended_function_key(qapp):
    rec = HotkeyRecorder("<f9>")
    rec._start_recording()
    _press(rec, _VK_F17)
    assert rec.value() == "<f17>"


def test_set_value_updates_display(qapp):
    rec = HotkeyRecorder("<f9>")
    rec.set_value("<right_alt>")
    assert rec.value() == "<right_alt>"
    assert rec._label.text() == "Right Option"
