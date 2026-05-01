"""Cloud-provider API key storage with keychain-primary, env-var-fallback semantics.

Realises ADR-0001 (`docs/adr/0001-api-key-storage.md`). One read path, two
sources, deterministic precedence:

1. ``keyring.get_password("murmuro", provider_id)`` — the OS keychain
   (macOS Keychain / Windows Credential Manager / Secret Service on
   Linux). This is where the Models page writes user-pasted keys.
2. The environment variable ``<PROVIDER_ID>_API_KEY`` (e.g.
   ``OPENAI_API_KEY``, ``GROQ_API_KEY``). Power users with direnv,
   1Password CLI, or shell rc files keep working without touching the UI.
   Callers may pass an explicit ``env_var=`` to honour a custom name
   configured per provider — used by the OpenAI flow where the env var
   name is configurable in ``config.toml`` for backwards compat.

The env-var fallback is **read-only**. ``set`` and ``delete`` only ever
touch the keychain — we never mutate the user's environment.

Failure modes mirror ``fn_monitor`` graceful degradation: any
``keyring`` import or call failure during ``get`` is logged at WARNING
and falls through to the env-var path so transcription keeps working
when the keychain is locked or unavailable. ``set`` does the opposite —
it raises, because silently dropping a save the user just clicked is
worse than surfacing the failure.
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

_SERVICE = "murmuro"


def _env_var_name(provider_id: str, env_var: str | None) -> str:
    return env_var if env_var else f"{provider_id.upper()}_API_KEY"


def get(provider_id: str, env_var: str | None = None) -> str | None:
    """Return the API key for ``provider_id`` or ``None`` if unset.

    Reads the keychain first; on miss or any keychain error, falls
    through to the env var. ``env_var`` overrides the default
    ``<PROVIDER_ID>_API_KEY`` name — pass it when the provider config
    carries a customised env var name.
    """
    try:
        import keyring

        value = keyring.get_password(_SERVICE, provider_id)
        if value:
            return value
    except Exception:  # noqa: BLE001 — never crash the caller; fall through.
        _log.warning("keyring lookup failed for %r; falling back to env var", provider_id,
                     exc_info=True)

    return os.environ.get(_env_var_name(provider_id, env_var)) or None


def set(provider_id: str, value: str) -> None:  # noqa: A001 — public API mirrors keyring.
    """Write ``value`` to the keychain under ``provider_id``.

    Raises on any keychain failure — the caller (typically the Models
    page Save handler) needs to know the key didn't persist.
    """
    import keyring

    keyring.set_password(_SERVICE, provider_id, value)


def delete(provider_id: str) -> None:
    """Remove ``provider_id`` from the keychain.

    Does not touch the env var — that's the user's environment, not
    ours. After delete, ``get`` will fall through to the env var if one
    is set.
    """
    import keyring

    keyring.delete_password(_SERVICE, provider_id)
