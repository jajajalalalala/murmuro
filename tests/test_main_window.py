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


def _silent_restart(*_args, **_kwargs) -> bool:
    """Stub for tests — never actually pop a modal QMessageBox or relaunch."""
    return False


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


def test_recording_a_new_hotkey_persists_via_apply(qapp):
    saved: list[config_mod.Config] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        confirm_restart_fn=_silent_restart,
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
        confirm_restart_fn=_silent_restart,
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
        confirm_restart_fn=_silent_restart,
    )
    win.shortcuts_page.hotkey_recorder.set_value("")
    win.home_page.auto_paste.setChecked(False)
    assert saved[-1].hotkey == "<right_alt>"  # stays at the original


def test_close_event_hides_instead_of_quitting(qapp):
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)
    win.show()
    win.close()
    assert not win.isVisible()
