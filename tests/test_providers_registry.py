"""Runtime-mutable provider registry: curated baseline + user-added entries.

Issue #17 turned ``providers.py`` from two module-level constants into a
``ProviderRegistry`` that combines a hardcoded curated baseline with
user-defined cloud providers persisted in ``config.toml``. These tests
cover the public read/mutation API, the curated-immutability rule,
keychain cleanup on unregister, and the TOML round-trip.
"""
from __future__ import annotations

import sys
import types

import pytest

from murmur import config as config_mod
from murmur import providers

# ---- Fakes -------------------------------------------------------------------

class _FakeKeyringErrors(types.ModuleType):
    class KeyringError(Exception):
        pass


class _FakeKeyring:
    """Dict-backed keyring stand-in. Same shape as test_secrets.py."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.delete_calls: list[str] = []
        self.delete_raises: Exception | None = None
        self.errors = _FakeKeyringErrors("keyring.errors")

    def get_password(self, service: str, key: str) -> str | None:
        return self.store.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.store[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        self.delete_calls.append(key)
        if self.delete_raises is not None:
            raise self.delete_raises
        self.store.pop((service, key), None)


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.errors", fake.errors)
    return fake


@pytest.fixture
def isolated_cfg(tmp_path, monkeypatch):
    """A Config bound to an on-disk TOML inside ``tmp_path``.

    The registry is a module-level singleton, so we rebind it to the
    fresh Config (and reset to the curated baseline) before each test
    and clean up afterwards.
    """
    monkeypatch.setattr(
        config_mod, "config_path", lambda: tmp_path / "config.toml",
    )
    cfg = config_mod.load()
    providers.reload_from_config(cfg)
    yield cfg
    # Reset to a baseline state so a failing test can't leak custom
    # providers into the next one.
    providers.reload_from_config(config_mod.Config())


# ---- Curated baseline --------------------------------------------------------


def test_list_local_returns_curated_baseline(isolated_cfg):
    locals_ = providers.list_local()
    ids = [m.id for m in locals_]
    assert "tiny" in ids
    assert "base" in ids
    assert "small" in ids
    assert "medium" in ids
    assert "large-v3" in ids
    assert "distil-large-v3" in ids


def test_list_cloud_returns_curated_openai_on_fresh_config(isolated_cfg):
    cloud = providers.list_cloud()
    assert [p.id for p in cloud] == ["openai"]
    assert cloud[0].base_url == "https://api.openai.com/v1"
    assert cloud[0].default_model == "whisper-1"
    assert cloud[0].curated is True


def test_get_cloud_finds_curated(isolated_cfg):
    p = providers.get_cloud("openai")
    assert p is not None
    assert p.id == "openai"


def test_get_cloud_returns_none_for_missing(isolated_cfg):
    assert providers.get_cloud("definitely-not-registered") is None


# ---- Register ----------------------------------------------------------------


def _custom_provider(provider_id: str = "my-minimax") -> providers.CloudProvider:
    return providers.CloudProvider(
        id=provider_id,
        label=f"{provider_id} display",
        base_url="https://api.minimax.io/v1",
        default_model="whisper-large",
        models=("whisper-large",),
        api_key_env=f"{provider_id.upper()}_API_KEY",
        rate_hint="",
        curated=False,
    )


def test_register_appears_in_list_cloud_and_persists(isolated_cfg, fake_keyring):
    providers.register(_custom_provider("my-minimax"))
    ids = [p.id for p in providers.list_cloud()]
    assert ids == ["openai", "my-minimax"]
    # Persisted to the bound config.
    assert [c.provider_id for c in isolated_cfg.custom_cloud] == ["my-minimax"]
    # And to the on-disk TOML.
    reloaded = config_mod.load()
    assert [c.provider_id for c in reloaded.custom_cloud] == ["my-minimax"]


def test_register_rejects_collision_with_curated(isolated_cfg, fake_keyring):
    with pytest.raises(ValueError, match="already registered"):
        providers.register(_custom_provider("openai"))


def test_register_rejects_collision_with_other_user_entry(isolated_cfg, fake_keyring):
    providers.register(_custom_provider("dup"))
    with pytest.raises(ValueError, match="already registered"):
        providers.register(_custom_provider("dup"))


def test_register_forces_curated_false_on_user_entries(isolated_cfg, fake_keyring):
    """Even if a caller passes ``curated=True`` we coerce to False so
    they can't sneak past the unregister guard later."""
    sneaky = providers.CloudProvider(
        id="sneaky",
        label="Sneaky",
        base_url="https://example.test",
        default_model="whisper-1",
        models=("whisper-1",),
        api_key_env="SNEAKY_API_KEY",
        rate_hint="",
        curated=True,
    )
    providers.register(sneaky)
    stored = providers.get_cloud("sneaky")
    assert stored is not None
    assert stored.curated is False


# ---- Unregister --------------------------------------------------------------


def test_unregister_removes_from_registry_and_config(isolated_cfg, fake_keyring):
    providers.register(_custom_provider("my-minimax"))
    providers.unregister("my-minimax")
    assert providers.get_cloud("my-minimax") is None
    assert isolated_cfg.custom_cloud == []
    reloaded = config_mod.load()
    assert reloaded.custom_cloud == []


def test_unregister_calls_secrets_delete(isolated_cfg, fake_keyring):
    fake_keyring.store[("murmur", "my-minimax")] = "sk-stored"
    providers.register(_custom_provider("my-minimax"))
    providers.unregister("my-minimax")
    assert "my-minimax" in fake_keyring.delete_calls
    assert ("murmur", "my-minimax") not in fake_keyring.store


def test_unregister_swallows_keychain_errors(isolated_cfg, fake_keyring):
    """A locked / missing keychain entry must not block the registry
    update — the user already clicked Remove and we owe them the
    visible removal even when the secret store is unreliable."""
    fake_keyring.delete_raises = fake_keyring.errors.KeyringError("locked")
    providers.register(_custom_provider("my-minimax"))
    # Should not raise.
    providers.unregister("my-minimax")
    assert providers.get_cloud("my-minimax") is None


def test_unregister_refuses_curated(isolated_cfg, fake_keyring):
    with pytest.raises(ValueError, match="curated"):
        providers.unregister("openai")
    # And openai is still in the list.
    assert providers.get_cloud("openai") is not None


def test_unregister_unknown_provider_raises(isolated_cfg, fake_keyring):
    with pytest.raises(ValueError, match="not registered"):
        providers.unregister("never-was")


# ---- reload_from_config + TOML round-trip -----------------------------------


def test_reload_from_config_rebuilds_from_disk(isolated_cfg, fake_keyring):
    providers.register(_custom_provider("first"))
    providers.register(_custom_provider("second"))
    # Drop runtime state by binding to a fresh empty config.
    providers.reload_from_config(config_mod.Config())
    assert [p.id for p in providers.list_cloud()] == ["openai"]
    # Re-binding to the persisted config restores both entries.
    reloaded = config_mod.load()
    providers.reload_from_config(reloaded)
    assert [p.id for p in providers.list_cloud()] == ["openai", "first", "second"]


def test_toml_roundtrip_preserves_custom_providers(isolated_cfg, fake_keyring):
    providers.register(_custom_provider("first"))
    providers.register(_custom_provider("second"))
    cfg2 = config_mod.load()
    assert [c.provider_id for c in cfg2.custom_cloud] == ["first", "second"]
    # And the registry view, when bound to the freshly-loaded config,
    # surfaces both with their persisted base_url / model.
    providers.reload_from_config(cfg2)
    cloud = {p.id: p for p in providers.list_cloud()}
    assert cloud["first"].base_url == "https://api.minimax.io/v1"
    assert cloud["second"].default_model == "whisper-large"


def test_register_without_bound_config_raises(monkeypatch):
    """Calling register before reload_from_config is a programmer error
    — the registry has nowhere to persist to. Surface it loudly rather
    than silently dropping the entry on the floor."""
    fresh = providers.ProviderRegistry()
    with pytest.raises(RuntimeError, match="not bound to a Config"):
        fresh.register(_custom_provider())


# ---- Custom provider config dataclass ---------------------------------------


def test_custom_cloud_provider_round_trips(tmp_path, monkeypatch):
    """``Config.custom_cloud`` survives a save/load cycle untouched."""
    monkeypatch.setattr(
        config_mod, "config_path", lambda: tmp_path / "config.toml",
    )
    cfg = config_mod.load()
    cfg.custom_cloud.append(
        config_mod.CustomCloudProvider(
            provider_id="my-minimax",
            display_name="My MiniMax",
            base_url="https://api.minimax.io/v1",
            model="whisper-large",
        )
    )
    config_mod.save(cfg)
    cfg2 = config_mod.load()
    assert len(cfg2.custom_cloud) == 1
    entry = cfg2.custom_cloud[0]
    assert entry.provider_id == "my-minimax"
    assert entry.display_name == "My MiniMax"
    assert entry.base_url == "https://api.minimax.io/v1"
    assert entry.model == "whisper-large"


def test_api_key_never_persists_to_toml(tmp_path, monkeypatch, fake_keyring):
    """Belt-and-braces: there's no field on ``CustomCloudProvider`` for
    a key, but explicitly assert the TOML written by ``save()`` after a
    register doesn't contain the keychain value."""
    monkeypatch.setattr(
        config_mod, "config_path", lambda: tmp_path / "config.toml",
    )
    cfg = config_mod.load()
    providers.reload_from_config(cfg)
    # Register a custom provider and write a key to the (fake) keychain
    # the way the Models page would.
    from murmur import secrets

    providers.register(_custom_provider("leaky"))
    secrets.set("leaky", "sk-very-secret")
    raw = (tmp_path / "config.toml").read_bytes()
    assert b"sk-very-secret" not in raw
