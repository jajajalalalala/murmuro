"""Hotkey spec parsing — covers the friendly-name aliases."""
from __future__ import annotations

import pytest

pytest.importorskip("pynput")

from pynput import keyboard  # noqa: E402

from murmuro.hotkey import FN_KEY, PushToTalkHotkey  # noqa: E402


def test_right_alt_alias():
    keys = PushToTalkHotkey._parse_keys("<right_alt>")
    assert keys == {keyboard.Key.alt_r}


def test_right_option_alias():
    keys = PushToTalkHotkey._parse_keys("<right_option>")
    assert keys == {keyboard.Key.alt_r}


def test_combo():
    keys = PushToTalkHotkey._parse_keys("<ctrl>+<shift>+<space>")
    assert keys == {keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space}


def test_native_pynput_name_still_works():
    keys = PushToTalkHotkey._parse_keys("<alt_r>")
    assert keys == {keyboard.Key.alt_r}


def test_fn_key_resolves_to_sentinel():
    """`<fn>` has no pynput Key on macOS — it routes through the FN_KEY
    sentinel that the listener bridges to the NSEvent global monitor."""
    keys = PushToTalkHotkey._parse_keys("<fn>")
    assert keys == {FN_KEY}


def test_fn_key_combo():
    keys = PushToTalkHotkey._parse_keys("<fn>+a")
    assert FN_KEY in keys
    assert any(getattr(k, "char", None) == "a" for k in keys)


def test_unknown_key_raises():
    with pytest.raises(ValueError, match="Unknown special key"):
        PushToTalkHotkey._parse_keys("<not_a_real_key>")
