"""Build a Transcriber from config."""
from __future__ import annotations

from .. import config as cfg_mod
from .base import Transcriber


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
        )
    if cfg.backend == "openai":
        from .. import secrets
        from .openai_api import OpenAIWhisper

        # Prefer the keychain entry written by the Models page; fall back
        # to the configured env var name for users who set up Murmur
        # before keychain storage existed (or who use direnv / 1Password
        # CLI). See `docs/adr/0001-api-key-storage.md`.
        api_key = secrets.get("openai", env_var=cfg.openai.api_key_env)
        if not api_key:
            raise RuntimeError(
                "OpenAI backend selected but no API key found. Add one on the Models "
                f"page or set the {cfg.openai.api_key_env} env var."
            )
        return OpenAIWhisper(api_key=api_key, model=cfg.openai.model)
    raise ValueError(f"Unknown backend: {cfg.backend!r}")
