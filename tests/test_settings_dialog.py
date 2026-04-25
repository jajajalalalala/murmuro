"""SettingsDialog: widgets reflect Config in, updated_config() reflects edits out."""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from murmur import config as config_mod  # noqa: E402
from murmur.settings_dialog import SettingsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication(sys.argv)


def _make_cfg() -> config_mod.Config:
    return config_mod.Config(
        backend="local",
        language="en",
        hotkey="<right_alt>",
        auto_paste=True,
        local=config_mod.LocalBackendConfig(model="base"),
        openai=config_mod.OpenAIBackendConfig(api_key_env="OPENAI_API_KEY"),
    )


def test_dialog_loads_existing_config(qapp):
    cfg = _make_cfg()
    dlg = SettingsDialog(cfg)
    assert dlg.hotkey_edit.text() == "<right_alt>"
    assert dlg.backend_combo.currentText() == "local"
    assert dlg.model_combo.currentText() == "base"
    assert dlg.language_combo.currentData() == "en"
    assert dlg.auto_paste.isChecked() is True


def test_dialog_round_trip_unchanged(qapp):
    cfg = _make_cfg()
    dlg = SettingsDialog(cfg)
    new = dlg.updated_config()
    assert new.hotkey == cfg.hotkey
    assert new.backend == cfg.backend
    assert new.language == cfg.language
    assert new.local.model == cfg.local.model


def test_dialog_applies_edits(qapp):
    cfg = _make_cfg()
    dlg = SettingsDialog(cfg)
    dlg.hotkey_edit.setText("<f9>")
    dlg.backend_combo.setCurrentText("openai")
    dlg.model_combo.setCurrentText("small")
    dlg.language_combo.setCurrentIndex(0)  # auto
    dlg.auto_paste.setChecked(False)

    new = dlg.updated_config()
    assert new.hotkey == "<f9>"
    assert new.backend == "openai"
    assert new.local.model == "small"
    assert new.language == "auto"
    assert new.auto_paste is False


def test_dialog_preserves_unknown_local_model(qapp):
    """If the existing config has a model we don't ship in the dropdown,
    we still surface it instead of silently overwriting."""
    cfg = _make_cfg()
    cfg.local.model = "distil-large-v3"
    dlg = SettingsDialog(cfg)
    assert dlg.model_combo.currentText() == "distil-large-v3"
    assert dlg.updated_config().local.model == "distil-large-v3"


def test_dialog_falls_back_when_hotkey_blank(qapp):
    cfg = _make_cfg()
    dlg = SettingsDialog(cfg)
    dlg.hotkey_edit.setText("   ")
    assert dlg.updated_config().hotkey == cfg.hotkey
