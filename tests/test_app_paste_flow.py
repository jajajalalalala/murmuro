"""End-to-end test for the press → release → transcribe → paste cycle.

Pinned regression test: when the user push-to-talks several times in a row,
every release must produce its own clean ⌘V CGEvent sequence with the
auto-repeat field set to 0. macOS marks unflagged synthesized repeats as
auto-repeats, which apps like Terminal and Electron-based editors silently
drop for shortcut chords — so the first paste of a session lands but every
subsequent one disappears with no error.

We drive MurmuroApp directly (no real microphone, no real Whisper), stub the
CoreGraphics ctypes bridge, and assert the same paste sequence is posted on
every cycle.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import numpy as np

from murmuro import inject
from murmuro.app import MurmuroApp, State
from murmuro.audio import SAMPLE_RATE
from murmuro.config import Config
from murmuro.permissions import AccessibilityStatus


def _one_second_of_audio() -> np.ndarray:
    return np.zeros(SAMPLE_RATE, dtype=np.float32)


def _fake_cg_libs():
    cg = MagicMock()
    cg.CGEventCreate.return_value = 0xF1A6
    cg.CGEventCreateKeyboardEvent.return_value = 0xBEEF
    cf = MagicMock()
    return cg, cf


def _drive_one_cycle(app: MurmuroApp, transcript: str) -> None:
    """Simulate hotkey-down, hotkey-up, wait for transcription thread."""
    transcribe_done = threading.Event()
    real_set_state = app._set_state

    def watch_set_state(s: State) -> None:
        real_set_state(s)
        if s is State.IDLE:
            transcribe_done.set()

    app._set_state = watch_set_state  # type: ignore[method-assign]
    app._transcriber = MagicMock()
    app._transcriber.transcribe.return_value = transcript

    app._on_press()
    app._on_release()
    assert transcribe_done.wait(timeout=2.0), "transcription thread never finished"


def test_three_consecutive_pastes_each_post_full_cmd_v_event():
    """Three press/release cycles → three full ⌘V sequences posted to the OS."""
    cfg = Config(auto_paste=True)
    cg, cf = _fake_cg_libs()

    def fake_cdll(path: str):
        if "CoreGraphics" in path:
            return cg
        if "CoreFoundation" in path:
            return cf
        raise AssertionError(f"unexpected CDLL: {path}")

    fake_recorder = MagicMock()
    fake_recorder.stop.return_value = _one_second_of_audio()

    with (
        patch("murmuro.app.Recorder", return_value=fake_recorder),
        patch.object(inject.pyperclip, "copy"),
        patch.object(inject.platform, "system", return_value="Darwin"),
        patch(
            "murmuro.permissions.accessibility_status",
            return_value=AccessibilityStatus.GRANTED,
        ),
        patch.object(inject.ctypes, "CDLL", side_effect=fake_cdll),
    ):
        app = MurmuroApp(cfg=cfg)
        for transcript in ("first", "second", "third"):
            _drive_one_cycle(app, transcript)

    # Three cycles × 2 keyboard events each.
    assert cg.CGEventCreateKeyboardEvent.call_count == 6
    keys = [c.args[1:] for c in cg.CGEventCreateKeyboardEvent.call_args_list]
    assert keys == [(9, True), (9, False)] * 3

    # Three cycles each post a flagsChanged-clear before the ⌘V chord.
    # Pinned regression: without this, modifier state from the user's
    # hotkey (especially right_alt = Right Option, a dead-key modifier)
    # stays sticky for ~1s and corrupts our ⌘V into ⌥⌘V at the receiver.
    assert cg.CGEventCreate.call_count == 3
    assert cg.CGEventSetType.call_count == 3
    for call in cg.CGEventSetType.call_args_list:
        assert call.args[1] == 12  # kCGEventFlagsChanged

    # SetFlags: 3 cycles × (1 clear + 2 ⌘V) = 9 calls; pattern [0, ⌘, ⌘] per cycle.
    flag_values = [c.args[1] for c in cg.CGEventSetFlags.call_args_list]
    assert flag_values == [0, 0x100000, 0x100000] * 3

    # Every v-event marked autorepeat=0 (field 8). Field is only set on
    # keyboard events, not on the flagsChanged event.
    assert cg.CGEventSetIntegerValueField.call_count == 6
    for call in cg.CGEventSetIntegerValueField.call_args_list:
        assert call.args[1] == 8
        assert call.args[2] == 0

    # 3 cycles × 3 posts each (flagsChanged + v-down + v-up) = 9 posts,
    # all to kCGAnnotatedSessionEventTap (= 2).
    assert cg.CGEventPost.call_count == 9
    for call in cg.CGEventPost.call_args_list:
        assert call.args[0] == 2


def test_paste_skipped_entirely_when_accessibility_denied():
    """Without Accessibility we must not touch CoreGraphics at all."""
    cfg = Config(auto_paste=True)

    fake_recorder = MagicMock()
    fake_recorder.stop.return_value = _one_second_of_audio()

    with (
        patch("murmuro.app.Recorder", return_value=fake_recorder),
        patch.object(inject.pyperclip, "copy") as copy,
        patch.object(inject.platform, "system", return_value="Darwin"),
        patch(
            "murmuro.permissions.accessibility_status",
            return_value=AccessibilityStatus.DENIED,
        ),
        patch.object(inject.ctypes, "CDLL") as cdll,
    ):
        app = MurmuroApp(cfg=cfg)
        _drive_one_cycle(app, "no permission")

    copy.assert_called_once_with("no permission")
    cdll.assert_not_called()


def test_clipboard_only_mode_never_posts_cg_events():
    """auto_paste=False: text reaches clipboard, no synthetic keystroke."""
    cfg = Config(auto_paste=False)

    fake_recorder = MagicMock()
    fake_recorder.stop.return_value = _one_second_of_audio()

    with (
        patch("murmuro.app.Recorder", return_value=fake_recorder),
        patch.object(inject.pyperclip, "copy") as copy,
        patch.object(inject.platform, "system", return_value="Darwin"),
        patch.object(inject.ctypes, "CDLL") as cdll,
    ):
        app = MurmuroApp(cfg=cfg)
        _drive_one_cycle(app, "clipboard only")

    copy.assert_called_once_with("clipboard only")
    cdll.assert_not_called()


def test_paste_request_callback_routes_through_host_ui_thread():
    """When the host wires on_paste_request, the worker delegates to it.

    Pinned regression: CGEventPost from a worker thread is silently filtered
    on Sonoma+ for ad-hoc-signed bundles, even with Accessibility granted.
    The host (tray.py) must marshal the paste onto its run-loop thread —
    this test verifies the worker honors that contract by calling the
    host's callback instead of `paste_at_cursor` directly.
    """
    cfg = Config(auto_paste=True)
    fake_recorder = MagicMock()
    fake_recorder.stop.return_value = _one_second_of_audio()
    received = []

    def host_paste(text: str) -> None:
        received.append(text)

    with (
        patch("murmuro.app.Recorder", return_value=fake_recorder),
        patch("murmuro.app.paste_at_cursor") as direct_paste,
        patch.object(inject.pyperclip, "copy"),
    ):
        app = MurmuroApp(cfg=cfg, on_paste_request=host_paste)
        _drive_one_cycle(app, "from worker")

    assert received == ["from worker"]
    direct_paste.assert_not_called()  # must NOT call paste_at_cursor on worker thread


def test_empty_transcript_skips_paste():
    """Empty transcripts must not invoke the paste path."""
    cfg = Config(auto_paste=True)

    fake_recorder = MagicMock()
    fake_recorder.stop.return_value = _one_second_of_audio()

    with (
        patch("murmuro.app.Recorder", return_value=fake_recorder),
        patch.object(inject.pyperclip, "copy") as copy,
        patch.object(inject.platform, "system", return_value="Darwin"),
        patch(
            "murmuro.permissions.accessibility_status",
            return_value=AccessibilityStatus.GRANTED,
        ),
        patch.object(inject.ctypes, "CDLL") as cdll,
    ):
        app = MurmuroApp(cfg=cfg)
        _drive_one_cycle(app, "")

    copy.assert_not_called()
    cdll.assert_not_called()
