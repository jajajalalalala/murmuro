"""Main window: pages render, edits round-trip into Config + persist.

Hotkey changes surface an explicit "Restart Murmur to apply?" modal —
Cancel is the default button so a stray Enter doesn't auto-fire the
relaunch (#38). Other axes (toggles, model/provider) hot-reload via
``MurmurApp.reload_config`` without a relaunch.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

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
    # Top nav: Home / Shortcuts / Models. About lives at the bottom of
    # the rail (its own one-item list). Stack still has 4 pages.
    assert win._nav_top.count() == 3
    assert win._nav_bottom.count() == 1
    assert win._stack.count() == 4
    assert win.home_page.auto_paste.isChecked() is True
    assert win.shortcuts_page.hotkey_recorder.value() == "<right_alt>"


def test_transcript_entry_includes_timestamp(qapp):
    """Each Home transcript row carries an HH:MM timestamp + the raw text.

    Transcripts now render as plain ``QWidget`` rows in a vertical
    layout (the previous QListWidget+setItemWidget rendering broke in
    bundled .app builds because the item size hint had width 0). Each
    row exposes ``text`` and ``timestamp`` attributes so this assertion
    can introspect without knowing the layout shape.
    """
    from datetime import datetime
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)
    when = datetime(2026, 4, 26, 14, 32, 5)
    win.append_transcript("hello world")  # uses now()
    win.home_page.add_transcript("test entry", when=when)
    row = win.home_page._rows[0]  # newest first
    assert row.text == "test entry"
    assert row.timestamp == "14:32"


def test_state_pushes_into_home(qapp):
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)
    win.update_state(State.RECORDING)
    assert win.home_page._state_text.text() == "Recording"
    win.update_state(State.IDLE)
    assert win.home_page._state_text.text() == "Idle"


def test_appended_transcripts_keep_only_last_n(qapp):
    """The panel is now session-scoped chat history (MAX_TRANSCRIPTS=200),
    not the previous "last 5 peek". Trimming still happens at the cap —
    overshoot the cap and confirm we never grow past it."""
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)
    cap = win.home_page.MAX_TRANSCRIPTS
    for i in range(cap + 5):
        win.append_transcript(f"line {i}")
    assert len(win.home_page._rows) == cap
    # Newest is on top.
    assert win.home_page._rows[0].text == f"line {cap + 4}"


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
    """Unchecking the play_beeps checkbox = entering silent mode."""
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
    relaunches: list[None] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        relaunch_fn=lambda: relaunches.append(None),
    )
    # Stub the modal as if the user clicked Restart so the save commits.
    with patch.object(MainWindow, "_confirm_hotkey_restart", return_value=True):
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
    )
    with patch.object(MainWindow, "_confirm_hotkey_restart", return_value=True):
        win.shortcuts_page.hotkey_recorder._commit("<f9>")
    assert saved, "save_config was never called after recorder committed"
    assert saved[-1].hotkey == "<f9>"


def test_blank_hotkey_falls_back_to_existing_value(qapp):
    saved: list[config_mod.Config] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        relaunch_fn=lambda: None,
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
    # Empty model → fallback prompts the user to pick one. The exact
    # copy ("pick one in Models") is the user-facing string we ship.
    assert "Models" in text and "pick" in text


def test_close_event_hides_instead_of_quitting(qapp):
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)
    win.show()
    win.close()
    assert not win.isVisible()


# --- Hotkey-change restart modal ----------------------------------------------


def test_hotkey_change_prompts_restart_modal(qapp):
    """A hotkey change must show the restart modal exactly once and only
    save when the user confirms."""
    saved: list[config_mod.Config] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        relaunch_fn=lambda: None,
    )
    with patch.object(
        MainWindow, "_confirm_hotkey_restart", return_value=True
    ) as confirm_mock:
        win.shortcuts_page.hotkey_recorder._commit("<f9>")

    confirm_mock.assert_called_once_with()
    assert saved and saved[-1].hotkey == "<f9>"


def test_unrelated_change_does_not_prompt_restart(qapp):
    """Toggling auto_paste must not surface the modal — only hotkey
    changes need a restart."""
    saved: list[config_mod.Config] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        relaunch_fn=lambda: None,
    )
    with patch.object(
        MainWindow, "_confirm_hotkey_restart"
    ) as confirm_mock:
        win.home_page.auto_paste.setChecked(False)

    assert saved and saved[-1].auto_paste is False
    confirm_mock.assert_not_called()


def test_model_change_alone_does_not_prompt_restart(qapp):
    """Local-model swaps ride MurmurApp.reload_config in-process (#46) —
    no restart needed, no modal."""
    saved: list[config_mod.Config] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        relaunch_fn=lambda: None,
    )

    def _mutate_local(draft):
        draft.local.model = "small"
        return draft

    win.home_page.apply_to_config = lambda c: c
    win.shortcuts_page.apply_to_config = lambda c: c
    win.models_page.apply_to_config = _mutate_local

    with patch.object(
        MainWindow, "_confirm_hotkey_restart"
    ) as confirm_mock:
        win._persist_changes()

    assert saved and saved[-1].local.model == "small"
    confirm_mock.assert_not_called()


def test_modal_cancel_does_not_save_or_relaunch(qapp):
    """Cancelling the modal must NOT persist the new hotkey and must
    leave the in-memory cfg + shortcuts widget pointing at the old one.
    That's the user-visible promise: the displayed hotkey matches what
    the running app is bound to."""
    saved: list[config_mod.Config] = []
    relaunches: list[None] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        relaunch_fn=lambda: relaunches.append(None),
    )
    original_hotkey = win._cfg.hotkey

    with patch.object(
        MainWindow, "_confirm_hotkey_restart", return_value=False
    ):
        win.shortcuts_page.hotkey_recorder._commit("<f9>")

    assert saved == [], "no save should land when the user cancels"
    assert relaunches == []
    assert win._cfg.hotkey == original_hotkey
    # And the widget must show the old hotkey again — the whole point.
    assert win.shortcuts_page.hotkey_recorder.value() == original_hotkey


def test_modal_restart_relaunches_via_qtimer(qapp):
    """A confirmed restart must defer the relaunch via QTimer so the
    QMessageBox can fully dismiss and _persist_changes can unwind before
    the process image is replaced."""
    from PySide6.QtTest import QTest

    saved: list[config_mod.Config] = []
    relaunches: list[None] = []
    win = MainWindow(
        _make_cfg(),
        save_config=saved.append,
        relaunch_fn=lambda: relaunches.append(None),
    )

    with patch.object(
        MainWindow, "_confirm_hotkey_restart", return_value=True
    ):
        win.shortcuts_page.hotkey_recorder._commit("<f9>")

    # Save lands synchronously; relaunch is deferred to the next tick.
    assert saved and saved[-1].hotkey == "<f9>"
    assert relaunches == [], "relaunch must not fire synchronously"

    QTest.qWait(20)
    assert relaunches == [None]


def test_confirm_modal_default_button_is_cancel(qapp):
    """Pin the Cancel-as-default detail by introspecting the QMessageBox
    constructed inside _confirm_hotkey_restart. A stray Enter from the
    recorder must NEVER fire the relaunch."""
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)

    fake_box = _FakeMessageBox(click_text="Cancel")
    with patch("murmur.main_window.QMessageBox", return_value=fake_box):
        confirmed = win._confirm_hotkey_restart()

    assert confirmed is False
    assert fake_box.default_button_text() == "Cancel"


def test_confirm_modal_returns_true_on_restart_click(qapp):
    win = MainWindow(_make_cfg(), save_config=lambda _c: None)

    fake_box = _FakeMessageBox(click_text="Restart now")
    with patch("murmur.main_window.QMessageBox", return_value=fake_box):
        confirmed = win._confirm_hotkey_restart()

    assert confirmed is True


class _FakeMessageBox:
    """Stand-in for ``QMessageBox`` that mimics just enough of the API for
    the prompt logic. ``exec()`` resolves the click by button text, so
    tests pick which button was 'clicked' by name rather than role.

    Why text and not role: production calls ``addButton(text, role)`` for
    both buttons, but ``QMessageBox.ButtonRole`` is a Qt enum that gets
    mocked when we patch the class — comparisons against the real enum
    misfire. Identifying by text avoids the real-vs-mock enum tangle."""

    def __init__(self, click_text: str) -> None:
        self._click_text = click_text
        self._buttons: list[tuple[object, str]] = []
        self.default_button: object = None
        self._clicked: object = None

    def setIcon(self, _icon) -> None:  # noqa: N802
        pass

    def setWindowTitle(self, _t) -> None:  # noqa: N802
        pass

    def setText(self, _t) -> None:  # noqa: N802
        pass

    def setInformativeText(self, _t) -> None:  # noqa: N802
        pass

    def addButton(self, text: str, _role) -> object:  # noqa: N802
        btn = object()  # opaque token; identity is all we compare
        self._buttons.append((btn, text))
        return btn

    def setDefaultButton(self, btn) -> None:  # noqa: N802
        self.default_button = btn

    def exec(self) -> int:
        for btn, text in self._buttons:
            if text == self._click_text:
                self._clicked = btn
                return 0
        return 0

    def clickedButton(self):  # noqa: N802
        return self._clicked

    def default_button_text(self) -> str | None:
        for btn, text in self._buttons:
            if btn is self.default_button:
                return text
        return None
