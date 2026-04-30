"""Main window: pages render, edits round-trip into Config + persist."""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from murmur import config as config_mod  # noqa: E402
from murmur.app import State  # noqa: E402
from murmur.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication(sys.argv)


class _FakeTray:
    """Minimal stand-in for QSystemTrayIcon — records showMessage calls."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def showMessage(self, title: str, body: str, *_args, **_kwargs) -> None:  # noqa: N802
        self.messages.append((title, body))


def _make_cfg() -> config_mod.Config:
    return config_mod.Config(
        backend="local",
        language="en",
        hotkey="<right_alt>",
        auto_paste=True,
        show_hud=True,
        local=config_mod.LocalBackendConfig(model="base"),
        openai=config_mod.OpenAIBackendConfig(api_key_env="OPENAI_API_KEY"),
    )


def test_window_constructs_with_four_pages(qapp):
    saved = []
    win = MainWindow(_make_cfg(), save_config=saved.append)
    # Four nav rows: Home / Shortcuts / Models / About.
    assert win._nav.count() == 4
    assert win._stack.count() == 4
    assert win.home_page.auto_paste.isChecked() is True
    assert win.shortcuts_page.hotkey_recorder.value() == "<right_alt>"


def test_transcript_entry_includes_timestamp(qapp):
    """Each Home transcript row carries an HH:MM prefix and the raw text."""
    from datetime import datetime
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)
    when = datetime(2026, 4, 26, 14, 32, 5)
    win.append_transcript("hello world")  # uses now()
    win.home_page.add_transcript("test entry", when=when)
    item = win.home_page._list.item(0)  # newest first
    assert item.text() == "14:32\ntest entry"
    assert item.data(0x0100) == "test entry"  # raw text retained for copy


def test_state_pushes_into_home(qapp):
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)
    win.update_state(State.RECORDING)
    assert win.home_page._state_text.text() == "Recording"
    win.update_state(State.IDLE)
    assert win.home_page._state_text.text() == "Idle"


def test_appended_transcripts_keep_only_last_n(qapp):
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)
    for i in range(7):
        win.append_transcript(f"line {i}")
    # MAX_TRANSCRIPTS = 5 in HomePage.
    assert win.home_page._list.count() == 5
    # Newest is on top.
    assert "line 6" in win.home_page._list.item(0).text()


def test_toggling_auto_paste_persists_and_emits(qapp):
    saved: list[config_mod.Config] = []
    emitted: list[config_mod.Config] = []
    win = MainWindow(_make_cfg(), save_config=saved.append)
    win.config_saved.connect(emitted.append)

    win.home_page.auto_paste.setChecked(False)

    assert saved, "save_config was never called after toggle"
    assert saved[-1].auto_paste is False
    assert emitted and emitted[-1].auto_paste is False


def test_silent_mode_toggle_persists_play_beeps(qapp):
    """Unchecking the play_beeps checkbox = entering silent mode. The
    change must round-trip through save_config so a relaunch keeps it."""
    saved: list[config_mod.Config] = []
    win = MainWindow(_make_cfg(), save_config=saved.append)
    assert win.home_page.play_beeps.isChecked() is True

    win.home_page.play_beeps.setChecked(False)  # enter silent mode

    assert saved, "save_config was never called after silent-mode toggle"
    assert saved[-1].play_beeps is False

    win.home_page.play_beeps.setChecked(True)   # exit silent mode
    assert saved[-1].play_beeps is True


def test_recording_a_new_hotkey_persists_via_apply(qapp):
    saved: list[config_mod.Config] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        relaunch_fn=lambda: None,
        restart_delay_ms=0,
    )
    # Simulate the recorder having captured a new spec, then trigger persist
    # by toggling the auto-paste checkbox (the simplest real signal).
    win.shortcuts_page.hotkey_recorder.set_value("<f9>")
    win.home_page.auto_paste.setChecked(False)
    assert saved[-1].hotkey == "<f9>"


def test_recorder_commit_alone_persists_new_hotkey(qapp):
    """Regression: recording a new hotkey without touching anything else
    on the page must still write to disk. Previously the page swallowed
    the recorder's commit, so the change only landed if the user also
    toggled an unrelated checkbox."""
    saved: list[config_mod.Config] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        relaunch_fn=lambda: None,
        restart_delay_ms=0,
    )
    # Drive the recorder through its real commit path — same code the
    # keyPressEvent handler runs after a non-modifier keypress.
    win.shortcuts_page.hotkey_recorder._commit("<f9>")
    assert saved, "save_config was never called after recorder committed"
    assert saved[-1].hotkey == "<f9>"


def test_blank_hotkey_falls_back_to_existing_value(qapp):
    saved: list[config_mod.Config] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        relaunch_fn=lambda: None,
        restart_delay_ms=0,
    )
    win.shortcuts_page.hotkey_recorder.set_value("")
    win.home_page.auto_paste.setChecked(False)
    assert saved[-1].hotkey == "<right_alt>"  # stays at the original


def test_home_summary_says_pick_a_model_when_local_is_empty(qapp):
    """Fresh install: the Home summary points the user at the Models page
    instead of showing 'Model ' with a blank value."""
    cfg = config_mod.Config(
        backend="local",
        language="auto",
        hotkey="<right_alt>",
        auto_paste=True,
        show_hud=True,
        local=config_mod.LocalBackendConfig(model=""),  # empty
        openai=config_mod.OpenAIBackendConfig(api_key_env="OPENAI_API_KEY"),
    )
    win = MainWindow(cfg, save_config=lambda _c: None)
    text = win.home_page._summary.text()
    assert "(none" in text and "Models" in text


def test_close_event_hides_instead_of_quitting(qapp):
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)
    win.show()
    win.close()
    assert not win.isVisible()


def test_hotkey_change_surfaces_tray_notification_and_relaunches(qapp):
    """Replacing the modal dialog: a hotkey change should fire a tray
    notification with the reason text, save the config, then call the
    relaunch function once the QTimer fires."""
    from PySide6.QtTest import QTest

    saved: list[config_mod.Config] = []
    relaunches: list[None] = []
    tray = _FakeTray()

    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        tray=tray,
        relaunch_fn=lambda: relaunches.append(None),
        restart_delay_ms=0,
    )
    win.shortcuts_page.hotkey_recorder._commit("<f9>")

    # Config persisted before any restart machinery runs.
    assert saved and saved[-1].hotkey == "<f9>"
    # Tray notification surfaced with the reason verbatim.
    assert tray.messages, "tray.showMessage was never called"
    title, body = tray.messages[-1]
    assert title == "Murmur"
    assert "the shortcut change" in body
    # Drain the event loop so the 0 ms QTimer fires.
    QTest.qWait(20)
    assert relaunches, "relaunch_fn was never called after the timer fired"


def test_unrelated_change_does_not_relaunch(qapp):
    """Toggling auto-paste must not surface a tray notification or
    schedule a relaunch — only model/provider/hotkey changes do."""
    from PySide6.QtTest import QTest

    saved: list[config_mod.Config] = []
    relaunches: list[None] = []
    tray = _FakeTray()

    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        tray=tray,
        relaunch_fn=lambda: relaunches.append(None),
        restart_delay_ms=0,
    )
    win.home_page.auto_paste.setChecked(False)

    QTest.qWait(20)
    assert saved and saved[-1].auto_paste is False
    assert tray.messages == []
    assert relaunches == []


def test_relaunch_works_without_tray(qapp):
    """Tests don't always wire a tray; the relaunch path must still fire."""
    from PySide6.QtTest import QTest

    relaunches: list[None] = []
    win = MainWindow(
        _make_cfg(),
        save_config=lambda _c: None,
        tray=None,
        relaunch_fn=lambda: relaunches.append(None),
        restart_delay_ms=0,
    )
    win.shortcuts_page.hotkey_recorder._commit("<f9>")
    QTest.qWait(20)
    assert relaunches, "relaunch_fn was never called when tray was None"
