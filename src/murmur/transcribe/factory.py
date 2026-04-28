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
        from .openai_api import OpenAIWhisper

        api_key = cfg_mod.openai_api_key(cfg)
        if not api_key:
            raise RuntimeError(
                f"OpenAI backend selected but env var {cfg.openai.api_key_env} is not set."
            )
        return OpenAIWhisper(api_key=api_key, model=cfg.openai.model)
    raise ValueError(f"Unknown backend: {cfg.backend!r}")
