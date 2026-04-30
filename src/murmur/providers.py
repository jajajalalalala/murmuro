"""Provider and model registry powering the Models page.

A provider is either:
  - ``local`` — a faster-whisper model that runs on the user's machine
    (no key, no network; downloads into Murmur's private model store —
    see ``transcribe.factory.default_local_download_root``).
  - ``openai_compatible`` — a hosted whisper-style endpoint reachable over
    HTTP with the OpenAI Python client (set ``base_url`` to point at the
    vendor; the curated OpenAI entry uses ``https://api.openai.com/v1``).

Shape: a curated baseline shipped in this module + a list of user-added
cloud providers persisted in ``config.toml`` under ``[[custom_cloud]]``.
The two are stitched together at runtime by ``ProviderRegistry``;
``list_local()`` and ``list_cloud()`` are the read paths the Models page
and the transcribe factory consume.

Adding a curated provider/model is a one-file change: append a row to
``_CURATED_LOCAL`` or ``_CURATED_CLOUD``. Adding a user-defined cloud
provider goes through ``register(...)``, which mutates the supplied
``Config`` and saves it. **API keys never appear in TOML** — they live
in the OS keychain via ``secrets.set(provider_id, value)``. See
ADR-0001 for the rationale.

Subscription/OAuth auth is intentionally out of scope (backlog). Each
``CloudProvider`` already carries an ``auth_methods`` tuple so we can add
``"oauth_chatgpt"`` later without restructuring callers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid circular import at runtime
    from .config import Config

# ---- Local (on-device) models -------------------------------------------------

@dataclass(frozen=True)
class LocalModel:
    """A faster-whisper model + metadata for the picker UI."""

    id: str            # passed verbatim to faster-whisper.WhisperModel
    label: str
    size_mb: int
    multilingual: bool

    def cache_path(self, download_root: str | os.PathLike[str] | None = None) -> Path:
        """Path faster-whisper writes this model to under ``download_root``.

        Used both to surface a "downloaded" signal in the UI and to drive
        the inline download progress bar. faster-whisper composes the
        per-model directory the same way HuggingFace's hub does:
        ``<root>/models--Systran--faster-whisper-<id>``.

        ``download_root`` is the resolved Murmur-private path (see
        ``transcribe.factory._resolve_local_download_root``). When
        ``None`` we fall back to the legacy HF cache resolution so
        early-boot callers — e.g. the Models page constructing rows
        before a config is plumbed in — still find pre-v0.6 downloads.
        New callers should always pass an explicit root.
        """
        if download_root is not None:
            cache_root = Path(download_root)
        else:
            cache_root = Path(
                os.environ.get("HF_HOME")
                or os.environ.get("HUGGINGFACE_HUB_CACHE")
                or Path.home() / ".cache" / "huggingface" / "hub"
            )
        return cache_root / f"models--Systran--faster-whisper-{self.id}"

    def is_downloaded(self, download_root: str | os.PathLike[str] | None = None) -> bool:
        path = self.cache_path(download_root)
        # Empty dirs (cancelled downloads) shouldn't count as ready.
        return path.is_dir() and any(path.iterdir())


# ---- Cloud (hosted) providers -------------------------------------------------

@dataclass(frozen=True)
class CloudProvider:
    """A hosted Whisper-style endpoint reachable via the OpenAI client."""

    id: str                         # stored in cfg.cloud_provider_id
    label: str
    base_url: str | None            # None = openai.com default (legacy);
                                    # curated entries now use absolute URLs
    default_model: str
    models: tuple[str, ...]
    api_key_env: str                # env var the user can drop their key into
    rate_hint: str                  # short string under the model picker
    auth_methods: tuple[str, ...] = ("api_key",)
    curated: bool = True            # False for user-added entries; immutable
                                    # API: curated entries refuse unregister.


# ---- Curated baseline ---------------------------------------------------------

_CURATED_LOCAL: tuple[LocalModel, ...] = (
    LocalModel("tiny",             "Tiny",                 75,   True),
    LocalModel("tiny.en",          "Tiny (English)",       75,   False),
    LocalModel("base",             "Base",                 145,  True),
    LocalModel("base.en",          "Base (English)",       145,  False),
    LocalModel("small",            "Small",                466,  True),
    LocalModel("small.en",         "Small (English)",      466,  False),
    LocalModel("medium",           "Medium",               1500, True),
    LocalModel("medium.en",        "Medium (English)",     1500, False),
    LocalModel("large-v3",         "Large v3",             3000, True),
    LocalModel("distil-large-v3",  "Distil Large v3 (EN)", 1500, False),
)

# Phase 1 ships with one wired-up cloud provider (OpenAI). Phase 2 fills
# the registry with Groq/Kimi/etc — they're just additional rows because
# they all speak the same OpenAI-compatible REST shape. #19 / #21 add
# user-facing UI for managing custom providers.
_CURATED_CLOUD: tuple[CloudProvider, ...] = (
    CloudProvider(
        id="openai",
        label="OpenAI Whisper",
        base_url="https://api.openai.com/v1",
        default_model="whisper-1",
        models=("whisper-1",),
        api_key_env="OPENAI_API_KEY",
        rate_hint="~$0.006 / minute",
        curated=True,
    ),
)


# ---- Runtime registry ---------------------------------------------------------

class ProviderRegistry:
    """Combined view of curated baseline + user-added cloud providers.

    The registry holds module-level singleton state (see the
    ``_REGISTRY`` instance below). Tests and ``app.py`` call
    ``reload_from_config(cfg)`` to rebuild that state from disk; the
    Models page and ``transcribe.factory`` call the read-only helpers.

    User-added providers persist via ``cfg.custom_cloud`` and a follow-up
    ``cfg.save()`` — never via direct mutation of TOML. API keys are
    written to the OS keychain via ``secrets.set(provider_id, value)``;
    they never appear in TOML. See ADR-0001.
    """

    def __init__(self) -> None:
        self._user_cloud: list[CloudProvider] = []
        self._cfg: Config | None = None

    # Read paths --------------------------------------------------------

    def list_local(self) -> list[LocalModel]:
        return list(_CURATED_LOCAL)

    def list_cloud(self) -> list[CloudProvider]:
        return list(_CURATED_CLOUD) + list(self._user_cloud)

    def get_cloud(self, provider_id: str) -> CloudProvider | None:
        return next(
            (p for p in self.list_cloud() if p.id == provider_id),
            None,
        )

    def find_local(self, model_id: str) -> LocalModel | None:
        return next((m for m in self.list_local() if m.id == model_id), None)

    # Mutation ----------------------------------------------------------

    def register(self, provider: CloudProvider) -> None:
        """Add a user-defined cloud provider and persist it.

        The provider is appended to ``cfg.custom_cloud`` (not the curated
        list) and ``cfg.save()`` is called immediately so the change
        survives a relaunch. API keys are **not** part of this call —
        the caller (the Models page, in #19 / #21) is responsible for
        writing the key to the keychain via
        ``secrets.set(provider.id, value)``. Storing keys in TOML is
        explicitly forbidden by ADR-0001.

        Raises ``ValueError`` on a provider-id collision with either the
        curated baseline or another user entry.
        """
        if self._cfg is None:
            raise RuntimeError(
                "ProviderRegistry is not bound to a Config — call "
                "reload_from_config(cfg) before register/unregister."
            )
        if self.get_cloud(provider.id) is not None:
            raise ValueError(
                f"provider id {provider.id!r} is already registered"
            )
        # Force the user-added marker so callers can't sneak in a curated
        # entry by passing curated=True.
        if provider.curated:
            provider = CloudProvider(
                id=provider.id,
                label=provider.label,
                base_url=provider.base_url,
                default_model=provider.default_model,
                models=provider.models,
                api_key_env=provider.api_key_env,
                rate_hint=provider.rate_hint,
                auth_methods=provider.auth_methods,
                curated=False,
            )
        self._user_cloud.append(provider)
        # Mirror into the bound Config so save() persists it.
        from .config import CustomCloudProvider
        from .config import save as save_cfg

        # Only persist api_key_env when the user provided a non-default
        # value — otherwise the empty string sticks and future loads
        # fall back to the auto-derived ``<PROVIDER_ID>_API_KEY`` rule.
        default_env = f"{provider.id.upper()}_API_KEY"
        api_key_env = (
            provider.api_key_env
            if provider.api_key_env and provider.api_key_env != default_env
            else ""
        )
        self._cfg.custom_cloud.append(
            CustomCloudProvider(
                provider_id=provider.id,
                display_name=provider.label,
                base_url=provider.base_url or "",
                model=provider.default_model,
                api_key_env=api_key_env,
            )
        )
        save_cfg(self._cfg)

    def unregister(self, provider_id: str) -> None:
        """Remove a user-added cloud provider; refuse for curated ones.

        Calls ``secrets.delete(provider_id)`` best-effort — a missing
        keychain entry is not an error. Persists the config.
        """
        if self._cfg is None:
            raise RuntimeError(
                "ProviderRegistry is not bound to a Config — call "
                "reload_from_config(cfg) before register/unregister."
            )
        if any(p.id == provider_id for p in _CURATED_CLOUD):
            raise ValueError(
                f"cannot unregister curated provider {provider_id!r}"
            )
        match_idx = next(
            (i for i, p in enumerate(self._user_cloud) if p.id == provider_id),
            None,
        )
        if match_idx is None:
            raise ValueError(f"provider id {provider_id!r} is not registered")
        self._user_cloud.pop(match_idx)
        self._cfg.custom_cloud = [
            c for c in self._cfg.custom_cloud if c.provider_id != provider_id
        ]
        from .config import save as save_cfg

        save_cfg(self._cfg)

        # Best-effort keychain cleanup. A missing entry is fine; any
        # other keyring failure (locked, backend down) is logged and
        # swallowed — the registry change must not be reverted just
        # because the keychain happens to be unavailable.
        from . import secrets

        try:
            secrets.delete(provider_id)
        except Exception:  # noqa: BLE001
            from ._logging import get_logger
            get_logger("providers").warning(
                "secrets.delete(%r) failed during unregister; ignoring",
                provider_id,
                exc_info=True,
            )

    def reload_from_config(self, cfg: Config) -> None:
        """Reset runtime state to ``curated_baseline + cfg.custom_cloud``.

        Called by ``app.py`` at startup and after config saves. Idempotent.
        """
        self._cfg = cfg
        self._user_cloud = [
            CloudProvider(
                id=c.provider_id,
                label=c.display_name,
                base_url=c.base_url or None,
                default_model=c.model,
                models=(c.model,),
                api_key_env=c.api_key_env or f"{c.provider_id.upper()}_API_KEY",
                rate_hint="",
                curated=False,
            )
            for c in cfg.custom_cloud
        ]


# Module-level singleton + thin functional facade. Mirrors how
# ``secrets.get / .set / .delete`` exposes a flat API while keeping
# state encapsulated.
_REGISTRY = ProviderRegistry()


def list_local() -> list[LocalModel]:
    return _REGISTRY.list_local()


def list_cloud() -> list[CloudProvider]:
    return _REGISTRY.list_cloud()


def get_cloud(provider_id: str) -> CloudProvider | None:
    return _REGISTRY.get_cloud(provider_id)


def register(provider: CloudProvider) -> None:
    _REGISTRY.register(provider)


def unregister(provider_id: str) -> None:
    _REGISTRY.unregister(provider_id)


def reload_from_config(cfg: Config) -> None:
    _REGISTRY.reload_from_config(cfg)


# ---- Back-compat helpers ------------------------------------------------------
#
# Existing callers (the Models page, `tests/test_providers.py`,
# `tests/test_models_page.py`) read module-level constants and use
# ``find_*`` helpers. Keep these as compatibility shims so this slice
# doesn't have to touch the UI; #19 / #21 will migrate the Models page
# wholesale when they add the management UI.

LOCAL_MODELS: tuple[LocalModel, ...] = _CURATED_LOCAL


def _curated_cloud_view() -> tuple[CloudProvider, ...]:
    """Curated cloud baseline — what the existing UI currently renders.

    Tests assert the legacy ``CLOUD_PROVIDERS`` constant matches the
    curated baseline (no user entries). Once #19 lands the management
    UI, callers migrate to ``list_cloud()``.
    """
    return _CURATED_CLOUD


CLOUD_PROVIDERS: tuple[CloudProvider, ...] = _CURATED_CLOUD


def find_local_model(model_id: str) -> LocalModel | None:
    return _REGISTRY.find_local(model_id)


def find_cloud_provider(provider_id: str) -> CloudProvider | None:
    return _REGISTRY.get_cloud(provider_id)
