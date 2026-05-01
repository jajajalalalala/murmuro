import pytest

from murmuro import config as config_mod
from murmuro.transcribe.factory import build


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "config_path", lambda: tmp_path / "config.toml")
    cfg = config_mod.load()
    assert cfg.backend == "local"
    cfg.backend = "cloud"
    cfg.cloud_provider_id = "openai"
    cfg.language = "en"
    config_mod.save(cfg)
    cfg2 = config_mod.load()
    assert cfg2.backend == "cloud"
    assert cfg2.cloud_provider_id == "openai"
    assert cfg2.language == "en"


def test_fresh_install_is_not_onboarded(tmp_path, monkeypatch):
    """A clean install starts with onboarded=False so the wizard fires
    on first launch (#20)."""
    monkeypatch.setattr(config_mod, "config_path", lambda: tmp_path / "config.toml")
    cfg = config_mod.load()
    assert cfg.onboarded is False


def test_existing_install_with_a_model_is_implicitly_onboarded(tmp_path, monkeypatch):
    """Migration: a config.toml that pre-dates the onboarded flag but
    has a local.model already picked is treated as onboarded — the
    user is mid-flight and we don't want to interrupt them with a
    wizard for things they've already done."""
    monkeypatch.setattr(config_mod, "config_path", lambda: tmp_path / "config.toml")
    legacy = b'backend = "local"\n[local]\nmodel = "base"\n'
    (tmp_path / "config.toml").write_bytes(legacy)
    cfg = config_mod.load()
    assert cfg.onboarded is True


def test_existing_install_without_a_model_still_runs_wizard(tmp_path, monkeypatch):
    """A pre-flag config without a picked model is treated as not
    onboarded so the wizard helps them finish setup."""
    monkeypatch.setattr(config_mod, "config_path", lambda: tmp_path / "config.toml")
    legacy = b'backend = "local"\n[local]\nmodel = ""\n'
    (tmp_path / "config.toml").write_bytes(legacy)
    cfg = config_mod.load()
    assert cfg.onboarded is False


def test_legacy_openai_backend_is_migrated_to_cloud(tmp_path, monkeypatch):
    """Pre-#17 configs stored ``backend = "openai"`` directly. Loading
    them should transparently produce the new (cloud, openai) shape so
    upgraders don't have to hand-edit their TOML."""
    monkeypatch.setattr(config_mod, "config_path", lambda: tmp_path / "config.toml")
    # Hand-write the legacy shape.
    legacy = b'backend = "openai"\nlanguage = "en"\n'
    (tmp_path / "config.toml").write_bytes(legacy)
    cfg = config_mod.load()
    assert cfg.backend == "cloud"
    assert cfg.cloud_provider_id == "openai"
    assert cfg.language == "en"


def test_fresh_install_has_no_local_model_selected():
    """A fresh Config() must not preselect a model.

    Otherwise the first push-to-talk silently downloads ~145 MB from
    HuggingFace before the user has consented or even seen the Models
    page. The user must explicitly click Use on a downloaded model.
    """
    cfg = config_mod.Config()
    assert cfg.local.model == ""


def test_load_creates_fresh_config_with_empty_model(tmp_path, monkeypatch):
    """First-run load() (no file on disk) writes the empty default."""
    monkeypatch.setattr(config_mod, "config_path", lambda: tmp_path / "config.toml")
    cfg = config_mod.load()
    assert cfg.local.model == ""
    # Round-trip through disk preserves the empty selection.
    reloaded = config_mod.load()
    assert reloaded.local.model == ""


def test_factory_refuses_to_build_local_with_empty_model():
    cfg = config_mod.Config(backend="local", local=config_mod.LocalBackendConfig(model=""))
    with pytest.raises(RuntimeError, match="No local model selected"):
        build(cfg)
