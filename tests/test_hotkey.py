"""Hotkey spec parsing + in-place rebinding via :meth:`replace_spec`."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("pynput")

from pynput import keyboard  # noqa: E402

from murmur.hotkey import FN_KEY, PushToTalkHotkey  # noqa: E402


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


# ─── replace_spec: in-place rebinding (#38) ────────────────────────────


def _make_hotkey(spec: str) -> tuple[PushToTalkHotkey, MagicMock, MagicMock]:
    on_press = MagicMock()
    on_release = MagicMock()
    h = PushToTalkHotkey(spec, on_press=on_press, on_release=on_release)
    return h, on_press, on_release


def test_replace_spec_old_keys_stop_firing():
    """After rebinding, the previous hotkey must no longer activate the
    callback. The listener thread keeps running and we just match a
    different target set."""
    h, on_press, _ = _make_hotkey("<right_alt>")
    h.replace_spec("<f9>")

    # Press the OLD key — must NOT fire on_press (it's no longer in the
    # target set).
    h._on_key_press(keyboard.Key.alt_r)
    on_press.assert_not_called()


def test_replace_spec_new_keys_start_firing():
    """The new hotkey activates the callback through the same listener
    instance — no stop+start dance, no race window."""
    h, on_press, on_release = _make_hotkey("<right_alt>")
    h.replace_spec("<f9>")

    h._on_key_press(keyboard.Key.f9)
    on_press.assert_called_once()
    h._on_key_release(keyboard.Key.f9)
    on_release.assert_called_once()


def test_replace_spec_clears_stale_held_keys():
    """If the user was holding the old hotkey when they hit Save, that
    chord wouldn't fire its release through the new target set —
    _held_keys would never converge back to empty. replace_spec resets
    state so the new chord activates cleanly on its first press."""
    h, on_press, _ = _make_hotkey("<right_alt>")
    # Simulate the old chord being held at the moment of save.
    h._on_key_press(keyboard.Key.alt_r)
    on_press.assert_called_once()
    on_press.reset_mock()

    h.replace_spec("<f9>")

    # Holding the old key any longer is a no-op; pressing the new key
    # activates fresh from a clean state.
    h._on_key_press(keyboard.Key.f9)
    on_press.assert_called_once()
    assert h._is_active is True
    h._on_key_release(keyboard.Key.f9)
    assert h._is_active is False


def test_replace_spec_combo_to_single_key():
    h, on_press, _ = _make_hotkey("<ctrl>+<shift>")
    h.replace_spec("<f13>")

    # Old combo half-presses must not activate.
    h._on_key_press(keyboard.Key.ctrl)
    h._on_key_press(keyboard.Key.shift)
    on_press.assert_not_called()

    h._on_key_press(keyboard.Key.f13)
    on_press.assert_called_once()


def test_replace_spec_starts_fn_monitor_when_newly_needed(monkeypatch):
    """Switching to <fn> must spin up an FnMonitor — pynput can't see
    flagsChanged for the macOS Fn modifier on its own."""
    started: list[object] = []
    fake_monitor = MagicMock()
    fake_monitor.start.return_value = True

    def make_monitor(*_args, **_kwargs):
        started.append(fake_monitor)
        return fake_monitor

    monkeypatch.setattr("murmur.hotkey.FnMonitor", make_monitor)

    h, *_ = _make_hotkey("<right_alt>")
    assert h._fn_monitor is None
    h.replace_spec("<fn>")
    assert h._fn_monitor is fake_monitor
    fake_monitor.start.assert_called_once()


def test_replace_spec_stops_fn_monitor_when_no_longer_needed(monkeypatch):
    """Switching away from <fn> must release the NSEvent monitor — leaving
    it attached would keep firing into a now-unused press handler."""
    fake_monitor = MagicMock()
    fake_monitor.start.return_value = True
    monkeypatch.setattr(
        "murmur.hotkey.FnMonitor", lambda *_a, **_kw: fake_monitor
    )

    h, *_ = _make_hotkey("<fn>")
    h._fn_monitor = fake_monitor  # simulate already-running monitor

    h.replace_spec("<f9>")
    assert h._fn_monitor is None
    fake_monitor.stop.assert_called_once()
