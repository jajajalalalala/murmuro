"""Build a Transcriber from config."""
from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir

from .. import config as cfg_mod
from .base import Transcriber

# Subdirectory under ``platformdirs.user_data_dir("Murmur")`` where
# faster-whisper writes downloaded models. Kept as a module-level
# constant so tests and uninstall.py can reference the same value.
_MODELS_SUBDIR = "models"


def default_local_download_root() -> Path:
    """Murmur's private model store path (no I/O).

    macOS:   ~/Library/Application Support/Murmur/models
    Windows: %LOCALAPPDATA%\\Murmur\\models
    Linux:   ~/.local/share/Murmur/models

    The directory is *not* created here — callers that actually need it
    (factory.build, uninstall) call ``_resolve_local_download_root``
    which creates it on demand.
    """
    return Path(user_data_dir(cfg_mod.APP_NAME)) / _MODELS_SUBDIR


def _resolve_local_download_root(cfg: cfg_mod.Config) -> str:
    """Resolve cfg.local.download_root to an existing on-disk directory.

    Empty-string config (the default) maps to the platformdirs path so
    we don't have to migrate existing TOML files when this lands. Any
    non-empty value is honored verbatim — power users can point Murmur
    at an external drive or a shared location.

    The returned path is guaranteed to exist (mkdir parents/exist_ok).
    """
    configured = cfg.local.download_root.strip() if cfg.local.download_root else ""
    root = Path(configured) if configured else default_local_download_root()
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def build(cfg: cfg_mod.Config) -> Transcriber:
    if cfg.backend == "local":
        if not cfg.local.model:
            # Fresh installs default to no selection — surface a friendly
            # message instead of letting faster-whisper crash with an opaque
            # path-resolution error.
            raise RuntimeError(
                "No local model selected. Open Murmur → Models and pick "
                "one (Tiny is fastest, Base is the recommended default)."
            )
        from .local import LocalWhisper

        return LocalWhisper(
            model=cfg.local.model,
            device=cfg.local.device,
            compute_type=cfg.local.compute_type,
            download_root=_resolve_local_download_root(cfg),
        )
    # Pre-#17 callers may still hand us cfg.backend == "openai" — config.load()
    # rewrites the on-disk value, but tests and direct construction don't go
    # through that. Treat the legacy string as an alias here so both paths
    # build the same OpenAI transcriber.
    if cfg.backend == "openai":
        cfg.backend = "cloud"
        cfg.cloud_provider_id = "openai"
    if cfg.backend == "cloud":
        from .. import providers, secrets
        from .openai_compatible import OpenAICompatible

        # Make sure the registry reflects whatever's in cfg.custom_cloud
        # before we look up the provider. ``app.py`` calls this on
        # startup, but the factory is sometimes invoked directly from
        # tests / the CLI, so we re-bind defensively. Idempotent.
        providers.reload_from_config(cfg)
        provider = providers.get_cloud(cfg.cloud_provider_id)
        if provider is None:
            raise ValueError(
                f"Unknown cloud provider: {cfg.cloud_provider_id!r} — "
                "check the Models page."
            )

        # Prefer the keychain entry written by the Models page; fall back
        # to the configured env var name for users who set up Murmur
        # before keychain storage existed (or who use direnv / 1Password
        # CLI). See `docs/adr/0001-api-key-storage.md`.
        env_var = (
            cfg.openai.api_key_env
            if provider.id == "openai"
            else provider.api_key_env
        )
        api_key = secrets.get(provider.id, env_var=env_var)
        if not api_key:
            raise RuntimeError(
                f"{provider.label} selected but no API key found. Add one on "
                f"the Models page or set the {env_var} env var."
            )
        # Per-provider model selection: openai keeps its existing
        # ``cfg.openai.model`` so legacy TOMLs round-trip; user-added
        # providers use the model captured in their custom entry.
        if provider.id == "openai":
            model = cfg.openai.model or provider.default_model
        else:
            model = provider.default_model
        return OpenAICompatible(
            base_url=provider.base_url,
            api_key=api_key,
            model=model,
        )
    raise ValueError(f"Unknown backend: {cfg.backend!r}")
