"""Models page: provider switching + local-model selection round-trip."""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from murmur import config as config_mod  # noqa: E402
from murmur.pages.models import ModelsPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication(sys.argv)


def _cfg(backend: str = "local", model: str = "base") -> config_mod.Config:
    return config_mod.Config(
        backend=backend,
        language="auto",
        hotkey="<right_alt>",
        auto_paste=True,
        show_hud=True,
        local=config_mod.LocalBackendConfig(model=model),
        openai=config_mod.OpenAIBackendConfig(api_key_env="OPENAI_API_KEY"),
    )


def test_initial_provider_matches_config(qapp):
    page = ModelsPage(_cfg(backend="local"))
    assert page.provider_combo.currentData() == "local"

    page = ModelsPage(_cfg(backend="openai"))
    assert page.provider_combo.currentData() == "openai"


def test_unknown_backend_falls_back_to_local(qapp):
    page = ModelsPage(_cfg(backend="some-unimplemented-provider"))
    assert page.provider_combo.currentData() == "local"


def test_apply_local_writes_active_model(qapp):
    page = ModelsPage(_cfg(backend="local", model="base"))
    page._local_panel._select_model("small")
    out = page.apply_to_config(_cfg(backend="local", model="base"))
    assert out.backend == "local"
    assert out.local.model == "small"


def test_apply_cloud_writes_provider_and_model(qapp):
    page = ModelsPage(_cfg(backend="openai"))
    out = page.apply_to_config(_cfg(backend="openai"))
    assert out.backend == "openai"
    assert out.openai.api_key_env == "OPENAI_API_KEY"
    assert out.openai.model == "whisper-1"


def test_custom_local_model_is_preserved(qapp):
    """A model that's not in LOCAL_MODELS still shows up so the user can
    keep using whatever they hand-edited into the TOML."""
    page = ModelsPage(_cfg(model="distil-large-v3-something-custom"))
    assert "distil-large-v3-something-custom" in page._local_panel._rows


def test_switching_to_cloud_reveals_cloud_panel(qapp):
    page = ModelsPage(_cfg(backend="local"))
    # Move the dropdown from local → openai.
    for i in range(page.provider_combo.count()):
        if page.provider_combo.itemData(i) == "openai":
            page.provider_combo.setCurrentIndex(i)
            break
    assert page._stack.currentWidget() is page._cloud_panel
