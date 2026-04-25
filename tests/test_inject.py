"""Tests for the clipboard / auto-paste injection helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from murmur import inject


def test_to_clipboard_empty_returns_false():
    assert inject.to_clipboard("") is False


def test_to_clipboard_copies_via_pyperclip():
    with patch.object(inject.pyperclip, "copy") as copy:
        assert inject.to_clipboard("hello") is True
        copy.assert_called_once_with("hello")


def test_paste_at_cursor_empty_short_circuits():
    assert inject.paste_at_cursor("") is False


def test_paste_at_cursor_copies_then_sends_modifier_v():
    fake_kb = MagicMock()
    fake_pressed = MagicMock()
    fake_pressed.__enter__ = MagicMock(return_value=None)
    fake_pressed.__exit__ = MagicMock(return_value=False)
    fake_kb.pressed = MagicMock(return_value=fake_pressed)

    with (
        patch.object(inject.pyperclip, "copy") as copy,
        patch("pynput.keyboard.Controller", return_value=fake_kb),
        patch("pynput.keyboard.Key") as fake_key,
    ):
        fake_key.cmd = "CMD"
        fake_key.ctrl = "CTRL"
        ok = inject.paste_at_cursor("hi")

    assert ok is True
    copy.assert_called_once_with("hi")
    fake_kb.press.assert_called_once_with("v")
    fake_kb.release.assert_called_once_with("v")


def test_paste_at_cursor_returns_false_when_keystroke_raises():
    with (
        patch.object(inject.pyperclip, "copy"),
        patch("pynput.keyboard.Controller", side_effect=RuntimeError("no a11y")),
    ):
        assert inject.paste_at_cursor("hi") is False


@pytest.mark.parametrize("system,expected_attr", [("Darwin", "cmd"), ("Linux", "ctrl")])
def test_paste_at_cursor_picks_platform_modifier(system, expected_attr):
    fake_kb = MagicMock()
    fake_pressed = MagicMock()
    fake_pressed.__enter__ = MagicMock(return_value=None)
    fake_pressed.__exit__ = MagicMock(return_value=False)
    fake_kb.pressed = MagicMock(return_value=fake_pressed)

    with (
        patch.object(inject.pyperclip, "copy"),
        patch("pynput.keyboard.Controller", return_value=fake_kb),
        patch("pynput.keyboard.Key") as fake_key,
        patch.object(inject.platform, "system", return_value=system),
    ):
        fake_key.cmd = "CMD"
        fake_key.ctrl = "CTRL"
        inject.paste_at_cursor("x")
        fake_kb.pressed.assert_called_once_with(getattr(fake_key, expected_attr))
