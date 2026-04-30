"""``transcribe.factory`` resolves the local-model download_root.

Issue #12 moved Murmur's model store from the shared HuggingFace cache
to a Murmur-private path under ``platformdirs.user_data_dir``. The
factory is the one place that materialises the empty-string default
into a real directory, so we exercise the resolution + on-demand
``mkdir`` behaviour here.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from platformdirs import user_data_dir

from murmur import config as config_mod
from murmur.transcribe.factory import (
    _resolve_local_download_root,
    default_local_download_root,
)


def test_default_path_matches_platformdirs():
    """The default lives under ``user_data_dir("Murmur") / "models"``."""
    expected = Path(user_data_dir("Murmur")) / "models"
    assert default_local_download_root() == expected


def test_resolve_returns_platformdirs_path_when_config_empty(tmp_path, monkeypatch):
    """Empty-string default → fall back to platformdirs."""
    fake = tmp_path / "data" / "Murmur" / "models"
    monkeypatch.setattr(
        "murmur.transcribe.factory.default_local_download_root",
        lambda: fake,
    )
    cfg = config_mod.Config(local=config_mod.LocalBackendConfig(download_root=""))
    resolved = _resolve_local_download_root(cfg)
    assert Path(resolved) == fake
    # mkdir-on-demand: the directory exists after resolve even though
    # nothing created it ahead of time.
    assert fake.exists()


def test_resolve_creates_missing_directory(tmp_path, monkeypatch):
    """The platformdirs path is created on first resolve."""
    fake = tmp_path / "deep" / "nested" / "models"
    assert not fake.exists()
    monkeypatch.setattr(
        "murmur.transcribe.factory.default_local_download_root",
        lambda: fake,
    )
    cfg = config_mod.Config(local=config_mod.LocalBackendConfig(download_root=""))
    _resolve_local_download_root(cfg)
    assert fake.is_dir()


def test_resolve_returns_configured_path_when_non_empty(tmp_path):
    """Non-empty config wins — power users can point Murmur elsewhere."""
    target = tmp_path / "elsewhere"
    cfg = config_mod.Config(
        local=config_mod.LocalBackendConfig(download_root=str(target)),
    )
    resolved = _resolve_local_download_root(cfg)
    assert Path(resolved) == target
    assert target.is_dir()


def test_resolve_strips_whitespace(tmp_path):
    """Defensive: a TOML field with leading/trailing space still resolves."""
    target = tmp_path / "spaced"
    cfg = config_mod.Config(
        local=config_mod.LocalBackendConfig(download_root=f"  {target}  "),
    )
    resolved = _resolve_local_download_root(cfg)
    assert Path(resolved) == target


def test_local_backend_config_default_download_root_is_empty():
    """The default is the empty string — TOML migration not required."""
    assert config_mod.LocalBackendConfig().download_root == ""


def test_config_save_load_preserves_download_root(tmp_path, monkeypatch):
    """The new field round-trips through the TOML file."""
    monkeypatch.setattr(
        config_mod, "config_path", lambda: tmp_path / "config.toml",
    )
    cfg = config_mod.load()
    cfg.local.download_root = str(tmp_path / "custom-store")
    config_mod.save(cfg)
    reloaded = config_mod.load()
    assert reloaded.local.download_root == str(tmp_path / "custom-store")


def test_build_local_passes_download_root(tmp_path, monkeypatch):
    """``build()`` plumbs the resolved root into ``LocalWhisper``."""
    target = tmp_path / "store"
    cfg = config_mod.Config(
        backend="local",
        local=config_mod.LocalBackendConfig(
            model="base",
            download_root=str(target),
        ),
    )
    from murmur.transcribe import factory as factory_mod

    transcriber = factory_mod.build(cfg)
    assert transcriber.download_root == str(target)
    assert target.is_dir()


def test_build_local_empty_download_root_uses_platformdirs(tmp_path, monkeypatch):
    fake = tmp_path / "data" / "Murmur" / "models"
    monkeypatch.setattr(
        "murmur.transcribe.factory.default_local_download_root",
        lambda: fake,
    )
    cfg = config_mod.Config(
        backend="local",
        local=config_mod.LocalBackendConfig(model="base"),
    )
    from murmur.transcribe import factory as factory_mod

    transcriber = factory_mod.build(cfg)
    assert Path(transcriber.download_root) == fake


def test_build_still_refuses_empty_model():
    cfg = config_mod.Config(
        backend="local",
        local=config_mod.LocalBackendConfig(model=""),
    )
    from murmur.transcribe import factory as factory_mod

    with pytest.raises(RuntimeError, match="No local model selected"):
        factory_mod.build(cfg)


# ---- Cloud-backend dispatch through the provider registry (#17) -------------


def test_legacy_openai_backend_still_builds(monkeypatch):
    """Pre-#17 ``backend = "openai"`` keeps producing an OpenAI
    transcriber pointed at api.openai.com without any TOML edits."""
    cfg = config_mod.Config(
        backend="openai",
        openai=config_mod.OpenAIBackendConfig(
            api_key_env="OPENAI_API_KEY", model="whisper-1"
        ),
    )
    monkeypatch.setattr(
        "murmur.secrets.get",
        lambda name, env_var=None: "sk-from-keychain",
    )
    from murmur.transcribe import factory as factory_mod

    transcriber = factory_mod.build(cfg)
    assert transcriber.base_url == "https://api.openai.com/v1"
    assert transcriber.api_key == "sk-from-keychain"
    assert transcriber.model == "whisper-1"


def test_cloud_backend_with_openai_provider_id_matches_legacy(monkeypatch):
    """Post-migration shape (backend=cloud, cloud_provider_id=openai)
    produces the same transcriber the legacy form did — proving the
    registry-driven dispatch is a drop-in for the hardcoded literal."""
    cfg = config_mod.Config(
        backend="cloud",
        cloud_provider_id="openai",
        openai=config_mod.OpenAIBackendConfig(
            api_key_env="OPENAI_API_KEY", model="whisper-1"
        ),
    )
    monkeypatch.setattr(
        "murmur.secrets.get",
        lambda name, env_var=None: "sk-from-keychain",
    )
    from murmur.transcribe import factory as factory_mod

    transcriber = factory_mod.build(cfg)
    assert transcriber.base_url == "https://api.openai.com/v1"
    assert transcriber.api_key == "sk-from-keychain"
    assert transcriber.model == "whisper-1"


def test_cloud_backend_dispatches_to_custom_provider(monkeypatch, tmp_path):
    """A user-added custom provider wired into cfg.cloud_provider_id is
    looked up via the registry and produces an OpenAICompatible with
    that provider's base_url + model."""
    monkeypatch.setattr(
        config_mod, "config_path", lambda: tmp_path / "config.toml",
    )
    from murmur import providers as providers_mod

    cfg = config_mod.load()
    providers_mod.reload_from_config(cfg)
    providers_mod.register(
        providers_mod.CloudProvider(
            id="my-minimax",
            label="My MiniMax",
            base_url="https://api.minimax.io/v1",
            default_model="whisper-large",
            models=("whisper-large",),
            api_key_env="MY_MINIMAX_API_KEY",
            rate_hint="",
            curated=False,
        )
    )
    cfg.backend = "cloud"
    cfg.cloud_provider_id = "my-minimax"

    captured = {}

    def fake_get(name, env_var=None):
        captured["name"] = name
        captured["env_var"] = env_var
        return "sk-minimax-key"

    monkeypatch.setattr("murmur.secrets.get", fake_get)
    from murmur.transcribe import factory as factory_mod

    transcriber = factory_mod.build(cfg)
    assert transcriber.base_url == "https://api.minimax.io/v1"
    assert transcriber.model == "whisper-large"
    assert transcriber.api_key == "sk-minimax-key"
    # The factory looked up the key under the provider id, with the
    # provider's configured env var name as the fallback.
    assert captured["name"] == "my-minimax"
    assert captured["env_var"] == "MY_MINIMAX_API_KEY"


def test_cloud_backend_unknown_provider_raises(monkeypatch):
    cfg = config_mod.Config(backend="cloud", cloud_provider_id="ghost")
    monkeypatch.setattr(
        "murmur.secrets.get",
        lambda name, env_var=None: "sk-",
    )
    from murmur.transcribe import factory as factory_mod

    with pytest.raises(ValueError, match="Unknown cloud provider"):
        factory_mod.build(cfg)
