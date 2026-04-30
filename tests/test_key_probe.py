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


# ─────────────────────────────────────────────────────────────────────────────
# Fn side-channel: NSEvent local monitor (matches HotkeyRecorder's path)
# ─────────────────────────────────────────────────────────────────────────────


class _FakeAppKit:
    NSEventMaskFlagsChanged = 1 << 12

    def __init__(self) -> None:
        self.added: list[object] = []
        self.removed: list[object] = []
        self._handlers: list = []

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

        def removeMonitor_(self, token):  # noqa: N802
            self._outer.removed.append(token)

    @property
    def NSEvent(self):  # noqa: N802
        return self._NSEventStub(self)

    def fire(self, flags: int) -> None:
        class _Event:
            def __init__(self, flags: int) -> None:
                self._flags = flags

            def modifierFlags(self):  # noqa: N802
                return self._flags

        for h in self._handlers:
            h(_Event(flags))


def _install_fake_appkit(monkeypatch) -> _FakeAppKit:
    import types

    fake = _FakeAppKit()
    monkeypatch.setitem(
        sys.modules,
        "AppKit",
        types.SimpleNamespace(
            NSEvent=fake.NSEvent,
            NSEventMaskFlagsChanged=fake.NSEventMaskFlagsChanged,
        ),
    )
    monkeypatch.setattr("murmur.fn_monitor.sys.platform", "darwin")
    return fake


_NS_FN_FLAG = 1 << 23


def test_fn_press_via_local_monitor_updates_probe(monkeypatch, qapp):
    """Real-hardware path: pressing Fn fires the NSEvent handler, the
    probe shows ``<fn>`` / "Modifier (works alone)"."""
    fake = _install_fake_appkit(monkeypatch)
    probe = KeyProbe()
    # Manually drive the focus lifecycle — offscreen Qt may not deliver
    # a real focus event by itself.
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QFocusEvent

    probe.focusInEvent(QFocusEvent(QFocusEvent.Type.FocusIn, _Qt.FocusReason.OtherFocusReason))
    assert len(fake.added) == 1
    fake.fire(_NS_FN_FLAG)
    assert probe.spec_text == "<fn>"
    assert "Modifier" in probe.kind_text

    probe.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut, _Qt.FocusReason.OtherFocusReason))
    assert fake.removed == fake.added
