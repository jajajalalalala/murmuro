"""Models page: provider switching + local-model selection round-trip."""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from murmuro import config as config_mod  # noqa: E402
from murmuro.pages.models import ModelsPage  # noqa: E402


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

    page = ModelsPage(_cfg(backend="cloud"))
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
    page = ModelsPage(_cfg(backend="cloud"))
    out = page.apply_to_config(_cfg(backend="cloud"))
    assert out.backend == "cloud"
    assert out.cloud_provider_id == "openai"
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


# ---- Download progress -----------------------------------------------------

def test_dir_size_bytes_sums_files_recursively(tmp_path):
    """The cache-size estimator walks all files under a directory."""
    from murmuro.pages.models import _dir_size_bytes
    (tmp_path / "a.bin").write_bytes(b"x" * 1024)
    sub = tmp_path / "snapshots"
    sub.mkdir()
    (sub / "model.bin").write_bytes(b"y" * 4096)
    assert _dir_size_bytes(tmp_path) == 1024 + 4096


def test_dir_size_bytes_handles_missing_dir(tmp_path):
    from murmuro.pages.models import _dir_size_bytes
    assert _dir_size_bytes(tmp_path / "does-not-exist") == 0


def test_set_progress_clamps_and_shows_bar(qapp):
    """Calling set_progress while downloading reveals the bar at the
    expected percentage (clamped to 99% so completion is owned by the
    finished signal, not the size poller)."""
    page = ModelsPage(_cfg())
    row = page._local_panel._rows["base"]
    row.set_downloading(True)
    row.set_progress(0.5)
    assert row._progress.isVisible() or row._progress.value() == 50
    assert row._progress.value() == 50
    # Beyond 100% → clamped just below to keep "finished" definitive.
    row.set_progress(1.5)
    assert row._progress.value() == 99


def test_set_progress_ignored_when_not_downloading(qapp):
    page = ModelsPage(_cfg())
    row = page._local_panel._rows["base"]
    # Default state: not downloading. Set should be a no-op.
    row.set_progress(0.7)
    assert row._progress.value() == 0


def test_set_downloading_false_resets_bar(qapp):
    page = ModelsPage(_cfg())
    row = page._local_panel._rows["base"]
    row.set_downloading(True)
    row.set_progress(0.6)
    row.set_downloading(False)
    assert row._progress.value() == 0


def test_poll_progress_updates_row_from_cache_size(qapp, monkeypatch):
    """End-to-end: a fake in-flight worker + a stubbed cache-size reader
    feeds the row's progress bar via _poll_progress."""
    from murmuro.pages import models as models_mod

    page = ModelsPage(_cfg())
    panel = page._local_panel
    row = panel._rows["tiny"]  # 75 MB target
    row.set_downloading(True)
    panel._workers["tiny"] = (None, None)  # marker so _poll_progress runs

    target = row.model.size_mb * 1024 * 1024
    monkeypatch.setattr(models_mod, "_dir_size_bytes", lambda _p: target // 2)
    panel._poll_progress()
    assert 45 <= row._progress.value() <= 55


# ---- Delete button --------------------------------------------------------

def _seed_fake_cache(monkeypatch, tmp_path, model_id: str):
    """Point Murmuro's private model store at tmp_path and seed ``model_id``.

    Mirrors what faster-whisper writes after a real download so
    ``LocalModel.is_downloaded(download_root)`` returns True. Pins the
    factory's platformdirs default to ``tmp_path`` so the Models page
    panel resolves there during construction.
    """
    monkeypatch.setattr(
        "murmuro.transcribe.factory.default_local_download_root",
        lambda: tmp_path,
    )
    cache_dir = tmp_path / f"models--Systran--faster-whisper-{model_id}"
    cache_dir.mkdir(parents=True)
    (cache_dir / "model.bin").write_bytes(b"fake-weights")
    return cache_dir


def test_delete_button_hidden_when_not_downloaded(qapp, monkeypatch, tmp_path):
    """Fresh model with no cache → only Download is visible."""
    monkeypatch.setattr(
        "murmuro.transcribe.factory.default_local_download_root",
        lambda: tmp_path,
    )
    page = ModelsPage(_cfg(model="base"))
    row = page._local_panel._rows["small"]
    assert row._action.text() == "Download"
    # The Delete slot stays in the layout so columns line up across
    # rows, but it's a non-interactive placeholder when not applicable
    # (no label, disabled, transparent via the ``placeholder`` style
    # property). Pre-redesign this row hid the button entirely.
    assert row._delete.isEnabled() is False
    assert row._delete.text() == ""
    assert row._delete.property("placeholder") is True


def test_delete_button_disabled_for_active_model(qapp, monkeypatch, tmp_path):
    """The active backend can't be deleted from underneath itself."""
    cache_dir = _seed_fake_cache(monkeypatch, tmp_path, "base")
    assert cache_dir.exists()
    page = ModelsPage(_cfg(model="base"))
    row = page._local_panel._rows["base"]
    assert row._is_active is True
    # Button is shown so users see it exists, but disabled with a tooltip.
    assert row._delete.isHidden() is False
    assert row._delete.isEnabled() is False
    assert "Switch to another model" in row._delete.toolTip()


def test_delete_button_enabled_for_downloaded_inactive_model(
    qapp, monkeypatch, tmp_path,
):
    _seed_fake_cache(monkeypatch, tmp_path, "small")
    page = ModelsPage(_cfg(model="base"))  # active is base, small is idle
    row = page._local_panel._rows["small"]
    assert row._delete.isHidden() is False
    assert row._delete.isEnabled() is True
    assert row._action.text() == "Use"


def test_delete_removes_cache_directory(qapp, monkeypatch, tmp_path):
    """End-to-end: Delete click → confirm → rmtree → row flips back to Download."""
    from murmuro.pages import models as models_mod

    cache_dir = _seed_fake_cache(monkeypatch, tmp_path, "small")
    monkeypatch.setattr(models_mod, "_confirm_delete", lambda *_a, **_k: True)

    page = ModelsPage(_cfg(model="base"))
    panel = page._local_panel
    row = panel._rows["small"]
    panel._delete_model("small")

    assert not cache_dir.exists(), "cache directory should be gone"
    assert row._action.text() == "Download"
    # Delete slot reverts to the placeholder state (see
    # test_delete_button_hidden_when_not_downloaded for the full
    # rationale).
    assert row._delete.isEnabled() is False
    assert row._delete.text() == ""


def test_delete_cancelled_keeps_files(qapp, monkeypatch, tmp_path):
    """If the user clicks Cancel, the cache stays intact."""
    from murmuro.pages import models as models_mod

    cache_dir = _seed_fake_cache(monkeypatch, tmp_path, "small")
    monkeypatch.setattr(models_mod, "_confirm_delete", lambda *_a, **_k: False)

    page = ModelsPage(_cfg(model="base"))
    page._local_panel._delete_model("small")
    assert cache_dir.exists()


def test_delete_refuses_active_model_even_if_called_directly(
    qapp, monkeypatch, tmp_path,
):
    """Belt-and-braces: the slot itself rejects the active model.

    The UI already disables the button, but we don't want a future
    refactor that wires this slot from elsewhere to silently nuke the
    model the user is currently transcribing through.
    """
    from murmuro.pages import models as models_mod

    cache_dir = _seed_fake_cache(monkeypatch, tmp_path, "base")
    confirmed = []
    monkeypatch.setattr(
        models_mod, "_confirm_delete",
        lambda *a, **k: (confirmed.append(True), True)[1],
    )

    page = ModelsPage(_cfg(model="base"))  # base is active
    page._local_panel._delete_model("base")
    # Never even prompted for confirmation, files untouched.
    assert confirmed == []
    assert cache_dir.exists()


def test_delete_model_files_handles_missing_dir(tmp_path):
    """Helper is a no-op if the path doesn't exist (defensive)."""
    from murmuro.pages.models import _delete_model_files
    _delete_model_files(tmp_path / "nope")  # must not raise


# ---- Fresh-install / empty-model behavior --------------------------------

def test_fresh_install_marks_no_row_active(qapp, monkeypatch, tmp_path):
    """With cfg.local.model='' (the new default), no row paints itself
    active and the Models page lists every shipped model with its real
    Download/Use state."""
    monkeypatch.setattr(
        "murmuro.transcribe.factory.default_local_download_root",
        lambda: tmp_path,
    )
    page = ModelsPage(_cfg(model=""))
    panel = page._local_panel
    assert panel.active_model_id == ""
    assert all(row._is_active is False for row in panel._rows.values())


def test_fresh_install_does_not_render_phantom_custom_row(qapp, monkeypatch, tmp_path):
    """Empty model must not produce a '(custom)' row labelled with ''."""
    monkeypatch.setattr(
        "murmuro.transcribe.factory.default_local_download_root",
        lambda: tmp_path,
    )
    page = ModelsPage(_cfg(model=""))
    assert "" not in page._local_panel._rows
