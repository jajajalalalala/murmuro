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


# --- Hot-reload regression net (#45) -----------------------------------------
#
# Post-#44, MurmurApp.reload_config drops the cached transcriber for
# model/provider/backend changes without restarting the pynput listener.
# _persist_changes therefore should *only* relaunch the process for hotkey
# changes — every other restart_reasons output rides the in-process
# config_saved -> reload_config path. These tests drive _persist_changes
# directly by stubbing each page's apply_to_config to mutate the draft
# the way the real widgets would, so we test the relaunch decision in
# isolation from Qt model/provider widget plumbing.


def _build_win_with_relaunch_capture(cfg, qapp):
    saved: list[config_mod.Config] = []
    relaunches: list[None] = []
    tray = _FakeTray()
    win = MainWindow(
        cfg,
        save_config=saved.append,
        tray=tray,
        relaunch_fn=lambda: relaunches.append(None),
        restart_delay_ms=0,
    )
    return win, saved, relaunches, tray


def _stub_pages(win, mutate):
    """Replace each page's apply_to_config with the identity, then plug
    ``mutate`` in as the models-page apply so the draft picks up the
    caller's desired change. Returns nothing — _persist_changes is
    invoked by the caller."""
    win.home_page.apply_to_config = lambda c: c
    win.shortcuts_page.apply_to_config = lambda c: c
    win.models_page.apply_to_config = mutate


def test_local_model_change_alone_does_not_relaunch(qapp):
    """Switching the active local model rides reload_config's transcriber
    drop — no os.execv needed."""
    from PySide6.QtTest import QTest

    cfg = _make_cfg()
    win, saved, relaunches, tray = _build_win_with_relaunch_capture(cfg, qapp)

    def _mutate(draft):
        draft.local.model = "small"
        return draft

    _stub_pages(win, _mutate)
    win._persist_changes()

    QTest.qWait(20)
    assert saved and saved[-1].local.model == "small"
    assert tray.messages == []
    assert relaunches == []


def test_cloud_provider_change_alone_does_not_relaunch(qapp):
    from PySide6.QtTest import QTest

    cfg = config_mod.Config(
        backend="cloud",
        cloud_provider_id="openai",
        hotkey="<right_alt>",
        local=config_mod.LocalBackendConfig(model="base"),
        openai=config_mod.OpenAIBackendConfig(api_key_env="OPENAI_API_KEY"),
    )
    win, saved, relaunches, tray = _build_win_with_relaunch_capture(cfg, qapp)

    def _mutate(draft):
        draft.cloud_provider_id = "groq"
        return draft

    _stub_pages(win, _mutate)
    win._persist_changes()

    QTest.qWait(20)
    assert saved and saved[-1].cloud_provider_id == "groq"
    assert tray.messages == []
    assert relaunches == []


def test_backend_switch_alone_does_not_relaunch(qapp):
    """Local <-> cloud no longer needs a process restart post-#44."""
    from PySide6.QtTest import QTest

    cfg = _make_cfg()  # backend="local"
    win, saved, relaunches, tray = _build_win_with_relaunch_capture(cfg, qapp)

    def _mutate(draft):
        draft.backend = "cloud"
        return draft

    _stub_pages(win, _mutate)
    win._persist_changes()

    QTest.qWait(20)
    assert saved and saved[-1].backend == "cloud"
    assert tray.messages == []
    assert relaunches == []


def test_combined_hotkey_and_model_change_relaunches_once_with_shortcut_reason(qapp):
    """When both a hotkey and a model change land in the same save, the
    hotkey change is the only one that can't be applied in-process. The
    relaunch should fire exactly once and the tray copy should mention
    the shortcut, not the model — that's the part actually requiring
    the os.execv."""
    from PySide6.QtTest import QTest

    cfg = _make_cfg()
    win, saved, relaunches, tray = _build_win_with_relaunch_capture(cfg, qapp)

    def _mutate_models(draft):
        draft.local.model = "small"
        return draft

    win.home_page.apply_to_config = lambda c: c
    win.models_page.apply_to_config = _mutate_models
    # Drive the hotkey through the recorder so the shortcuts page apply
    # picks it up the same way the real UI does.
    win.shortcuts_page.hotkey_recorder.set_value("<f9>")

    win._persist_changes()

    QTest.qWait(20)
    assert saved and saved[-1].hotkey == "<f9>"
    assert saved[-1].local.model == "small"
    assert len(relaunches) == 1, "expected exactly one relaunch"
    assert len(tray.messages) == 1
    _, body = tray.messages[-1]
    assert "shortcut" in body
    assert "model" not in body


def test_pure_toggle_save_does_not_relaunch(qapp):
    """Regression net: auto_paste flip must not surface a tray
    notification or relaunch. (Already true post-#44 because
    restart_reasons returns [] for pure toggles, but pin it.)"""
    from PySide6.QtTest import QTest

    cfg = _make_cfg()
    win, saved, relaunches, tray = _build_win_with_relaunch_capture(cfg, qapp)
    win.home_page.auto_paste.setChecked(False)

    QTest.qWait(20)
    assert saved and saved[-1].auto_paste is False
    assert tray.messages == []
    assert relaunches == []
