import pytest

from murmur import config as config_mod
from murmur.transcribe.factory import build


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
