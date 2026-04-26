"""Restart prompt: reason builder + main-window integration."""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from murmur import config as config_mod  # noqa: E402
from murmur.main_window import MainWindow  # noqa: E402
from murmur.restart import restart_reasons  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication(sys.argv)


def _cfg() -> config_mod.Config:
    return config_mod.Config()


# ---------- pure logic --------------------------------------------------


def test_no_change_no_reason():
    assert restart_reasons(_cfg(), _cfg()) == []


def test_backend_swap_calls_out_provider_change():
    a = _cfg()
    b = _cfg()
    b.backend = "openai"
    assert restart_reasons(a, b) == ["the model provider change"]


def test_local_model_swap_calls_out_model_change():
    a = _cfg()
    b = _cfg()
    b.local.model = "small"
    assert restart_reasons(a, b) == ["the model change"]


def test_openai_model_swap_only_counts_when_backend_is_openai():
    a = _cfg()
    a.backend = "openai"
    b = _cfg()
    b.backend = "openai"
    b.openai.model = "gpt-4o-transcribe"
    assert restart_reasons(a, b) == ["the model change"]


def test_local_model_change_ignored_when_backend_is_openai():
    """If the user is using the cloud backend, swapping the local-model
    placeholder shouldn't pop a restart prompt."""
    a = _cfg()
    a.backend = "openai"
    b = _cfg()
    b.backend = "openai"
    b.local.model = "small"
    assert restart_reasons(a, b) == []


def test_hotkey_change_calls_out_shortcut_change():
    a = _cfg()
    b = _cfg()
    b.hotkey = "<f9>"
    assert restart_reasons(a, b) == ["the shortcut change"]


def test_provider_change_takes_precedence_over_model_field():
    """Switching local→openai should report the provider reason, not
    duplicate-report a stale model field."""
    a = _cfg()
    b = _cfg()
    b.backend = "openai"
    b.local.model = "small"
    assert restart_reasons(a, b) == ["the model provider change"]


# ---------- main_window integration -------------------------------------


def test_persist_triggers_prompt_on_model_change(qapp, tmp_path):
    saved: list[config_mod.Config] = []
    prompts: list[str] = []

    cfg = _cfg()
    win = MainWindow(
        cfg,
        save_config=saved.append,
        confirm_restart_fn=lambda reason, parent=None, **_: prompts.append(reason) or False,
    )

    # Simulate the user changing the local model on the Models page.
    win.models_page._local_panel._select_model("small")
    win._persist_changes()

    assert saved and saved[-1].local.model == "small"
    assert prompts == ["the model change"]


def test_persist_no_prompt_when_only_unrelated_pref_changes(qapp):
    saved: list[config_mod.Config] = []
    prompts: list[str] = []

    cfg = _cfg()
    original_auto_paste = cfg.auto_paste
    win = MainWindow(
        cfg,
        save_config=saved.append,
        confirm_restart_fn=lambda reason, parent=None, **_: prompts.append(reason) or False,
    )

    # Toggle auto-paste — config persists but no restart should be requested.
    win.home_page.auto_paste.setChecked(not original_auto_paste)
    win._persist_changes()

    assert saved and saved[-1].auto_paste != original_auto_paste
    assert prompts == []
