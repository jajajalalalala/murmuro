"""Tests for `murmuro.secrets`.

The real `keyring` library is never imported here. CI runs headless with
no keychain backend; even if `keyring` were installed, calling
`keyring.set_password` against a real macOS Keychain would prompt the
user and pollute their login keychain. Instead we install a tiny
dict-backed fake module into `sys.modules["keyring"]` for the duration
of each test — `murmuro.secrets` lazy-imports `keyring` inside each
function, so the fake is what it sees.
"""
from __future__ import annotations

import logging
import sys
import types

import pytest

from murmuro import secrets


class _FakeKeyringErrors(types.ModuleType):
    class KeyringError(Exception):
        pass


class _FakeKeyring:
    """Dict-backed stand-in for the `keyring` top-level module."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.get_raises: Exception | None = None
        self.set_raises: Exception | None = None
        self.delete_raises: Exception | None = None
        # Mirrors `keyring.errors` so callers can `except
        # keyring.errors.KeyringError`.
        self.errors = _FakeKeyringErrors("keyring.errors")

    def get_password(self, service: str, key: str) -> str | None:
        if self.get_raises is not None:
            raise self.get_raises
        return self.store.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        if self.set_raises is not None:
            raise self.set_raises
        self.store[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        if self.delete_raises is not None:
            raise self.delete_raises
        self.store.pop((service, key), None)


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = _FakeKeyring()
    # secrets.py does `import keyring` lazily inside each function, so
    # patching sys.modules is enough — no need to reload anything.
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.errors", fake.errors)
    return fake


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Strip any provider env vars the host shell may have set."""
    for var in ("OPENAI_API_KEY", "GROQ_API_KEY", "TEST_API_KEY", "CUSTOM_NAME"):
        monkeypatch.delenv(var, raising=False)


def test_get_returns_keychain_value_when_present(fake_keyring):
    fake_keyring.store[("murmuro", "openai")] = "sk-keychain"
    assert secrets.get("openai") == "sk-keychain"


def test_get_falls_through_to_env_var_when_keychain_empty(fake_keyring, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert secrets.get("openai") == "sk-from-env"


def test_get_returns_none_when_neither_set(fake_keyring):
    assert secrets.get("openai") is None


def test_get_with_custom_env_var_name(fake_keyring, monkeypatch):
    monkeypatch.setenv("CUSTOM_NAME", "sk-custom")
    # Default rule would look for TEST_API_KEY; explicit override wins.
    assert secrets.get("test", env_var="CUSTOM_NAME") == "sk-custom"


def test_get_keychain_takes_precedence_over_env(fake_keyring, monkeypatch):
    fake_keyring.store[("murmuro", "openai")] = "sk-keychain"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert secrets.get("openai") == "sk-keychain"


def test_set_writes_to_keychain(fake_keyring):
    secrets.set("groq", "gsk-abc")
    assert fake_keyring.store == {("murmuro", "groq"): "gsk-abc"}


def test_delete_removes_from_keychain(fake_keyring):
    fake_keyring.store[("murmuro", "openai")] = "sk-key"
    secrets.delete("openai")
    assert ("murmuro", "openai") not in fake_keyring.store


def test_get_after_delete_falls_through_to_env(fake_keyring, monkeypatch):
    fake_keyring.store[("murmuro", "openai")] = "sk-key"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-fallback")
    secrets.delete("openai")
    assert secrets.get("openai") == "sk-env-fallback"


@pytest.fixture
def secrets_log_records():
    """List-backed handler attached directly to `murmuro.secrets`.

    pytest's built-in `caplog` listens via the root logger, but
    `murmuro._logging.setup_logging` sets `propagate=False` on the
    `murmuro` logger tree. Once any earlier test in the run triggers
    that setup, records emitted by `murmuro.secrets` never reach root
    and `caplog.records` stays empty. Attaching here sidesteps that.
    """
    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _ListHandler(level=logging.WARNING)
    log = logging.getLogger("murmuro.secrets")
    prev_level = log.level
    log.addHandler(handler)
    log.setLevel(logging.WARNING)
    try:
        yield records
    finally:
        log.removeHandler(handler)
        log.setLevel(prev_level)


def test_get_keychain_error_falls_through_to_env(fake_keyring, monkeypatch, secrets_log_records):
    fake_keyring.get_raises = fake_keyring.errors.KeyringError("backend unavailable")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert secrets.get("openai") == "sk-env"
    assert any("keyring lookup failed" in r.getMessage() for r in secrets_log_records)


def test_get_keychain_error_returns_none_when_no_env(fake_keyring, secrets_log_records):
    fake_keyring.get_raises = fake_keyring.errors.KeyringError("backend unavailable")
    assert secrets.get("openai") is None
    assert any("keyring lookup failed" in r.getMessage() for r in secrets_log_records)


def test_set_keychain_error_propagates(fake_keyring):
    fake_keyring.set_raises = fake_keyring.errors.KeyringError("locked")
    with pytest.raises(fake_keyring.errors.KeyringError):
        secrets.set("openai", "sk-key")


def test_default_env_var_rule_uppercases_provider_id(fake_keyring, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-env")
    assert secrets.get("groq") == "gsk-env"


def test_empty_string_in_keychain_treated_as_miss(fake_keyring, monkeypatch):
    """A blank keychain entry shouldn't shadow a real env var."""
    fake_keyring.store[("murmuro", "openai")] = ""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert secrets.get("openai") == "sk-env"
