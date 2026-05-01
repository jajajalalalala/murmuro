"""Tests for the clipboard / auto-paste injection helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from murmuro import inject


def test_to_clipboard_empty_returns_false():
    assert inject.to_clipboard("") is False


def test_to_clipboard_copies_via_pyperclip():
    with patch.object(inject.pyperclip, "copy") as copy:
        assert inject.to_clipboard("hello") is True
        copy.assert_called_once_with("hello")


def test_paste_at_cursor_empty_short_circuits():
    assert inject.paste_at_cursor("") is False


def _fake_cg_libs():
    """Build (cg, cf) mocks that pretend to be CoreGraphics + CoreFoundation."""
    cg = MagicMock()
    cg.CGEventCreate.return_value = 0xF1A6  # flagsChanged event
    cg.CGEventCreateKeyboardEvent.return_value = 0xBEEF
    cf = MagicMock()
    return cg, cf


def test_paste_at_cursor_macos_posts_cmd_v_via_coregraphics():
    from murmuro.permissions import AccessibilityStatus

    cg, cf = _fake_cg_libs()

    def fake_cdll(path):
        if "CoreGraphics" in path:
            return cg
        if "CoreFoundation" in path:
            return cf
        raise AssertionError(f"unexpected CDLL: {path}")

    with (
        patch.object(inject.pyperclip, "copy") as copy,
        patch.object(inject.platform, "system", return_value="Darwin"),
        patch(
            "murmuro.permissions.accessibility_status",
            return_value=AccessibilityStatus.GRANTED,
        ),
        patch.object(inject.ctypes, "CDLL", side_effect=fake_cdll),
    ):
        ok = inject.paste_at_cursor("hi")

    assert ok is True
    copy.assert_called_once_with("hi")
    # NULL source on each event (empirically what TCC accepts from this bundle).
    for call in cg.CGEventCreateKeyboardEvent.call_args_list:
        assert call.args[0] is None
    # v-down then v-up, posted to session tap; Cmd flag on both, autorepeat=0.
    keys = [c.args[1:] for c in cg.CGEventCreateKeyboardEvent.call_args_list]
    assert keys == [(9, True), (9, False)]
    # SetFlags called 3 times: once on the flagsChanged-clear (with 0), then
    # Cmd on each v event.
    flag_values = [c.args[1] for c in cg.CGEventSetFlags.call_args_list]
    assert flag_values == [0, 0x100000, 0x100000]
    # The flagsChanged event is created and stamped with type 12.
    cg.CGEventCreate.assert_called_once_with(None)
    cg.CGEventSetType.assert_called_once()
    assert cg.CGEventSetType.call_args.args[1] == 12  # kCGEventFlagsChanged
    # Both v events explicitly marked as not-an-autorepeat.
    assert cg.CGEventSetIntegerValueField.call_count == 2
    for call in cg.CGEventSetIntegerValueField.call_args_list:
        assert call.args[1] == 8
        assert call.args[2] == 0
    # 3 posts total: flagsChanged-clear + v-down + v-up, all to session tap.
    assert cg.CGEventPost.call_count == 3
    for call in cg.CGEventPost.call_args_list:
        assert call.args[0] == 2  # kCGAnnotatedSessionEventTap
    # 3 releases: flagsChanged event + v-down + v-up.
    assert cf.CFRelease.call_count == 3


def test_paste_at_cursor_macos_returns_false_when_event_creation_null():
    from murmuro.permissions import AccessibilityStatus

    cg, cf = _fake_cg_libs()
    cg.CGEventCreateKeyboardEvent.return_value = 0  # NULL

    def fake_cdll(path):
        return cg if "CoreGraphics" in path else cf

    with (
        patch.object(inject.pyperclip, "copy"),
        patch.object(inject.platform, "system", return_value="Darwin"),
        patch(
            "murmuro.permissions.accessibility_status",
            return_value=AccessibilityStatus.GRANTED,
        ),
        patch.object(inject.ctypes, "CDLL", side_effect=fake_cdll),
    ):
        assert inject.paste_at_cursor("hi") is False


def test_paste_at_cursor_skips_keystroke_when_accessibility_denied():
    """No paste attempt without Accessibility — text stays clipboard-only."""
    from murmuro.permissions import AccessibilityStatus

    with (
        patch.object(inject.pyperclip, "copy") as copy,
        patch.object(inject.platform, "system", return_value="Darwin"),
        patch(
            "murmuro.permissions.accessibility_status",
            return_value=AccessibilityStatus.DENIED,
        ),
        patch.object(inject.ctypes, "CDLL") as cdll,
    ):
        ok = inject.paste_at_cursor("hello")
    assert ok is False
    copy.assert_called_once_with("hello")
    cdll.assert_not_called()  # never touched CoreGraphics


def test_paste_at_cursor_linux_uses_pynput_ctrl_v():
    fake_kb = MagicMock()
    fake_pressed = MagicMock()
    fake_pressed.__enter__ = MagicMock(return_value=None)
    fake_pressed.__exit__ = MagicMock(return_value=False)
    fake_kb.pressed = MagicMock(return_value=fake_pressed)

    with (
        patch.object(inject.pyperclip, "copy"),
        patch.object(inject.platform, "system", return_value="Linux"),
        patch("pynput.keyboard.Controller", return_value=fake_kb),
        patch("pynput.keyboard.Key") as fake_key,
    ):
        fake_key.ctrl = "CTRL"
        ok = inject.paste_at_cursor("x")

    assert ok is True
    fake_kb.pressed.assert_called_once_with("CTRL")
    fake_kb.press.assert_called_once_with("v")
    fake_kb.release.assert_called_once_with("v")
