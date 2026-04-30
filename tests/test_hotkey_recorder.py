"""HotkeyRecorder: simulate Qt key events, verify the captured pynput spec."""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFocusEvent, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from murmur.hotkey_recorder import (  # noqa: E402
    CAPTURE_PLACEHOLDER,
    HotkeyRecorder,
    humanize,
)


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
_VK_FN = 0x3F
_VK_LEFT_ARROW = 0x7B
_VK_PAGE_UP = 0x74
_VK_KP_5 = 0x57
_VK_DIGIT_5 = 0x17  # top-row 5
_VK_LETTER_A = 0x00
_VK_SEMICOLON = 0x29


def _focus_in(widget: HotkeyRecorder) -> None:
    """Drive the focus-in path the way a real click would.

    Offscreen Qt doesn't always deliver a real focus event from
    ``setFocus`` on its own, so call the handler explicitly — same
    pattern as ``test_key_probe.py``.
    """
    widget.focusInEvent(
        QFocusEvent(QFocusEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason)
    )


def _focus_out(widget: HotkeyRecorder) -> None:
    widget.focusOutEvent(
        QFocusEvent(QFocusEvent.Type.FocusOut, Qt.FocusReason.MouseFocusReason)
    )


def _capture(widget: HotkeyRecorder) -> HotkeyRecorder:
    """Convenience: enter capture mode and return the widget."""
    _focus_in(widget)
    return widget


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


def test_focus_enters_capture_mode(qapp):
    """Focusing the widget swaps the placeholder and turns on the capture
    visual state — no Record button click required."""
    rec = HotkeyRecorder("<f9>")
    assert not rec.is_capturing
    assert rec._label.text() == "F9"
    _focus_in(rec)
    assert rec.is_capturing
    assert rec._label.text() == CAPTURE_PLACEHOLDER
    # Property is set so a stylesheet selector ([capturing="true"]) or a
    # test can detect the violet-ring state without parsing CSS.
    assert rec._label.property("capturing") is True


def test_modifier_only_hotkey_committed_on_release(qapp):
    """Press Right Option, release it → '<right_alt>' captured."""
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_RIGHT_ALT)
    assert rec.is_capturing  # not yet committed; user still holding
    _release(rec, _VK_RIGHT_ALT)
    assert rec.value() == "<right_alt>"


def test_combo_with_non_modifier_committed_on_press(qapp):
    """Ctrl+Shift+Space → committed as soon as Space goes down."""
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_LEFT_CTRL)
    _press(rec, _VK_LEFT_SHIFT)
    _press(rec, _VK_SPACE)
    assert rec.value() == "<left_ctrl>+<left_shift>+<space>"


def test_function_key_alone(qapp):
    """F9 alone → '<f9>' (non-modifier commits on press)."""
    rec = _capture(HotkeyRecorder("<right_alt>"))
    _press(rec, _VK_F9)
    assert rec.value() == "<f9>"


def test_letter_key_with_modifier(qapp):
    """Ctrl + A — letter detected via event.text(), not VK table."""
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_LEFT_CTRL)
    _press(rec, vk=0, text="a")  # vk=0 forces fall-through to text()
    assert rec.value() == "<left_ctrl>+a"


def test_escape_cancels_and_reverts(qapp):
    """Esc with nothing held → exit capture mode, revert to previous value."""
    rec = _capture(HotkeyRecorder("<right_alt>"))
    ev = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )
    rec.keyPressEvent(ev)
    # ``clearFocus`` may not fire focusOutEvent on offscreen Qt — drive it.
    _focus_out(rec)
    assert rec.value() == "<right_alt>"
    assert not rec.is_capturing
    assert rec._label.text() == "Right Option"


def test_focus_loss_cancels_and_reverts(qapp):
    """Clicking outside the field while in capture mode reverts."""
    rec = _capture(HotkeyRecorder("<right_alt>"))
    # User starts holding a modifier, then changes their mind and clicks
    # somewhere else before releasing.
    _press(rec, _VK_LEFT_CTRL)
    _focus_out(rec)
    assert rec.value() == "<right_alt>"  # unchanged
    assert not rec.is_capturing
    assert rec._label.text() == "Right Option"


def test_clear_button_clears_binding(qapp):
    """The × button empties the spec and emits value_changed("")."""
    rec = HotkeyRecorder("<right_alt>")
    emitted: list[str] = []
    rec.value_changed.connect(emitted.append)
    rec._clear_button.click()
    assert rec.value() == ""
    assert emitted == [""]
    assert rec._label.text() == "(none)"


def test_clear_idempotent_on_empty(qapp):
    """Clearing an already-empty field stays empty and emits nothing."""
    rec = HotkeyRecorder("")
    emitted: list[str] = []
    rec.value_changed.connect(emitted.append)
    rec._clear_button.click()
    assert rec.value() == ""
    assert emitted == []


def test_backspace_while_focused_clears(qapp):
    """Backspace inside capture mode clears the binding (power-user shortcut)."""
    rec = _capture(HotkeyRecorder("<right_alt>"))
    emitted: list[str] = []
    rec.value_changed.connect(emitted.append)
    ev = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Backspace,
        Qt.KeyboardModifier.NoModifier,
    )
    rec.keyPressEvent(ev)
    _focus_out(rec)
    assert rec.value() == ""
    assert emitted == [""]


def test_after_clearing_new_capture_works(qapp):
    """Once cleared, refocusing and pressing a key starts a fresh capture."""
    rec = HotkeyRecorder("<right_alt>")
    rec._clear_button.click()
    _focus_in(rec)
    assert rec._label.text() == CAPTURE_PLACEHOLDER
    _press(rec, _VK_F9)
    assert rec.value() == "<f9>"


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
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_LEFT_SHIFT)
    # Qt would deliver text="%" for shifted 5 — the recorder must ignore
    # event.text() and use the VK to recover the physical key.
    _press(rec, _VK_DIGIT_5, text="%")
    assert rec.value() == "<left_shift>+5"


def test_letter_via_vk_table(qapp):
    """Letter resolved by VK even with no event.text()."""
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_LETTER_A)
    assert rec.value() == "a"


def test_punctuation_via_vk_unshifted(qapp):
    """Shift+; should commit as '<left_shift>+;', not ':'."""
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_LEFT_SHIFT)
    _press(rec, _VK_SEMICOLON, text=":")
    assert rec.value() == "<left_shift>+;"


def test_fn_recorded_as_modifier(qapp):
    """Fn alone → '<fn>' (treated as modifier, commits on release)."""
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_FN)
    assert rec.is_capturing  # still held, not yet committed
    _release(rec, _VK_FN)
    assert rec.value() == "<fn>"


def test_fn_humanizes_to_fn(qapp):
    assert humanize("<fn>") == "Fn"


def test_caps_lock_recorded_as_modifier(qapp):
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_CAPS_LOCK)
    _release(rec, _VK_CAPS_LOCK)
    assert rec.value() == "<caps_lock>"


def test_navigation_cluster_keys(qapp):
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_PAGE_UP)
    assert rec.value() == "<page_up>"

    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_LEFT_ARROW)
    assert rec.value() == "<left>"


def test_keypad_digit_collapses_to_top_row_glyph(qapp):
    """Keypad keys share a spec with their top-row equivalents so pynput
    (which has no keypad enum on macOS) can still bind the resulting
    hotkey."""
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_KP_5)
    assert rec.value() == "5"


def test_extended_function_key(qapp):
    rec = _capture(HotkeyRecorder("<f9>"))
    _press(rec, _VK_F17)
    assert rec.value() == "<f17>"


def test_set_value_updates_display(qapp):
    rec = HotkeyRecorder("<f9>")
    rec.set_value("<right_alt>")
    assert rec.value() == "<right_alt>"
    assert rec._label.text() == "Right Option"


# ─────────────────────────────────────────────────────────────────────────────
# Fn side-channel: NSEvent local monitor
# ─────────────────────────────────────────────────────────────────────────────
# Cocoa never delivers ``keyDown:`` for Fn (it shows up only as
# ``flagsChanged:`` with NSEventModifierFlagFunction = 0x800000), so Qt's
# ``keyPressEvent`` never fires for it. The recorder installs an NSEvent
# local monitor while a capture session is active, tied to the focus
# lifecycle (matches KeyProbe). These tests stub the AppKit shim so they
# run on any platform.


class _FakeAppKit:
    """Minimal AppKit stand-in: records monitor add / remove calls and
    exposes a ``fire(flags)`` helper so tests can drive the handler."""

    NSEventMaskFlagsChanged = 1 << 12  # value irrelevant; we only check identity

    def __init__(self) -> None:
        self.added: list[object] = []  # opaque tokens we've handed out
        self.removed: list[object] = []
        self._handlers: list = []  # parallel to ``added``: the callback to fire
        self._next_token = 0

    # NSEvent surface -----------------------------------------------------

    class _NSEventStub:
        def __init__(self, outer: _FakeAppKit) -> None:
            self._outer = outer

        def addLocalMonitorForEventsMatchingMask_handler_(  # noqa: N802
            self, mask, handler
        ):
            token = object()
            self._outer.added.append(token)
            self._outer._handlers.append(handler)
            return token

        def addGlobalMonitorForEventsMatchingMask_handler_(  # noqa: N802
            self, mask, handler
        ):
            return self.addLocalMonitorForEventsMatchingMask_handler_(mask, handler)

        def removeMonitor_(self, token):  # noqa: N802
            self._outer.removed.append(token)

    @property
    def NSEvent(self):  # noqa: N802 (mirrors the AppKit name)
        return self._NSEventStub(self)

    # Test-side helpers ---------------------------------------------------

    def fire(self, flags: int) -> None:
        """Invoke every installed handler with a fake flagsChanged event."""

        class _Event:
            def __init__(self, flags: int) -> None:
                self._flags = flags

            def modifierFlags(self):  # noqa: N802 (mirrors NSEvent)
                return self._flags

        for h in self._handlers:
            h(_Event(flags))


def _install_fake_appkit(monkeypatch) -> _FakeAppKit:
    """Patch ``sys.platform`` to ``darwin`` and inject a fake ``AppKit``
    module so :class:`FnFocusMonitor` can import it."""
    import types

    fake = _FakeAppKit()
    fake_module = types.SimpleNamespace(
        NSEvent=fake.NSEvent,
        NSEventMaskFlagsChanged=fake.NSEventMaskFlagsChanged,
    )
    monkeypatch.setitem(sys.modules, "AppKit", fake_module)
    monkeypatch.setattr("murmur.fn_monitor.sys.platform", "darwin")
    return fake


_NS_FN_FLAG = 1 << 23


def test_focus_in_installs_fn_monitor(monkeypatch, qapp):
    """``FnFocusMonitor`` is armed in ``focusInEvent`` and torn down in
    ``focusOutEvent`` — matching the lifecycle the issue asks for."""
    fake = _install_fake_appkit(monkeypatch)
    rec = HotkeyRecorder("<f9>")
    assert fake.added == []  # not yet focused — nothing armed
    _focus_in(rec)
    assert len(fake.added) == 1
    assert fake.removed == []
    _focus_out(rec)
    # Exactly one monitor install / one teardown per focus cycle.
    assert fake.removed == fake.added


def test_fn_press_via_local_monitor_commits(monkeypatch, qapp):
    """Real-hardware path: the user presses Fn, NSEvent fires the handler,
    the recorder commits ``<fn>`` and (on the subsequent focusOut) tears
    the monitor down."""
    fake = _install_fake_appkit(monkeypatch)
    rec = HotkeyRecorder("<f9>")
    _focus_in(rec)

    # Rising edge: Fn down — recorder treats it as a held modifier.
    fake.fire(_NS_FN_FLAG)
    assert rec.is_capturing  # not yet committed; user still holding Fn
    assert rec._max_modifier_combo == ["<fn>"]

    # Falling edge: Fn up — modifier-only commit fires.
    fake.fire(0)
    # ``_commit`` calls ``clearFocus``; offscreen Qt may not fire focusOut
    # automatically, so drive it explicitly to assert the monitor cleanup.
    _focus_out(rec)
    assert rec.value() == "<fn>"
    assert not rec.is_capturing
    assert fake.removed == fake.added


def test_focus_out_tears_down_fn_monitor(monkeypatch, qapp):
    """If the user clicks away mid-session (Fn still held), the monitor
    must still come down. The recorder reverts in that case."""
    fake = _install_fake_appkit(monkeypatch)
    rec = HotkeyRecorder("<right_alt>")
    _focus_in(rec)
    fake.fire(_NS_FN_FLAG)  # press Fn
    _focus_out(rec)
    # Monitor torn down.
    assert fake.removed == fake.added
    # Original spec preserved (focus loss = cancel).
    assert rec.value() == "<right_alt>"


def test_fn_monitor_noop_off_macos(monkeypatch, qapp):
    """On non-darwin platforms the monitor must not attempt to import
    AppKit; entering and leaving capture mode should still be safe and
    the recorder should otherwise behave normally."""
    monkeypatch.setattr("murmur.fn_monitor.sys.platform", "linux")
    rec = HotkeyRecorder("<f9>")
    _focus_in(rec)
    # Existing modifier-only path still works exactly as before.
    _press(rec, _VK_RIGHT_ALT)
    _release(rec, _VK_RIGHT_ALT)
    assert rec.value() == "<right_alt>"
