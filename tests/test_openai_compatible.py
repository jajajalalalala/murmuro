"""Tests for the single OpenAI-compatible cloud transcriber and its
construction via ``transcribe.factory.build``.

ADR-0002 collapses all cloud backends (OpenAI, Groq, DeepSeek, custom
endpoints) onto one class parameterised by ``(base_url, api_key,
model)``. These tests are the regression net for that contract.
"""
from __future__ import annotations

import io
import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# The cloud-transcription tests below patch ``openai.OpenAI``, which
# requires the ``openai`` package to be importable. It lives in the
# ``[openai]`` optional extra (not in ``[dev]`` or ``[gui]``), so CI
# environments that install ``-e .[dev,gui]`` don't have it. Skip the
# whole module rather than fail with a confusing ModuleNotFoundError
# from inside the patch context manager.
pytest.importorskip("openai")

from murmuro import config as config_mod  # noqa: E402
from murmuro.transcribe.factory import build  # noqa: E402
from murmuro.transcribe.openai_compatible import (  # noqa: E402
    OpenAICompatible,
    _pcm_to_wav_bytes,
)


def test_constructor_rejects_empty_api_key():
    with pytest.raises(ValueError, match="API key is empty"):
        OpenAICompatible(base_url="https://api.openai.com/v1", api_key="", model="whisper-1")


def test_constructor_does_not_instantiate_client_eagerly():
    """The OpenAI client must only be built on the first transcribe()
    call. This keeps cold-start cheap and keeps tests from needing a
    network-aware mock just to construct the object."""
    with patch("openai.OpenAI") as mock_openai:
        OpenAICompatible(
            base_url="https://api.groq.com/openai/v1",
            api_key="fake",
            model="whisper-large-v3",
        )
        mock_openai.assert_not_called()


def test_base_url_is_plumbed_into_openai_client():
    """The whole point of the collapse: ``base_url`` must reach the
    underlying ``openai.OpenAI(...)`` constructor unchanged."""
    transcriber = OpenAICompatible(
        base_url="https://api.groq.com/openai/v1",
        api_key="fake",
        model="whisper-large-v3",
    )
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(text="hello")
    with patch("openai.OpenAI", return_value=fake_client) as mock_openai:
        out = transcriber.transcribe(np.zeros(16, dtype=np.float32), 16000)
    mock_openai.assert_called_once_with(
        api_key="fake",
        base_url="https://api.groq.com/openai/v1",
    )
    assert out == "hello"


def test_transcribe_short_circuits_on_empty_pcm():
    transcriber = OpenAICompatible(
        base_url="https://api.openai.com/v1", api_key="fake", model="whisper-1"
    )
    with patch("openai.OpenAI") as mock_openai:
        result = transcriber.transcribe(np.array([], dtype=np.float32), 16000)
    assert result == ""
    mock_openai.assert_not_called()


def test_pcm_to_wav_bytes_roundtrip():
    pcm = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    wav = _pcm_to_wav_bytes(pcm, 16000)
    with wave.open(io.BytesIO(wav), "rb") as r:
        assert r.getnchannels() == 1
        assert r.getsampwidth() == 2
        assert r.getframerate() == 16000
        assert r.getnframes() == len(pcm)


def test_factory_builds_openai_compatible_for_openai_backend(monkeypatch):
    """Existing OpenAI flow keeps working: factory.build returns a
    transcriber whose constructor args match what was previously passed
    to OpenAIWhisper, plus the OpenAI default base URL."""
    cfg = config_mod.Config(
        backend="openai",
        openai=config_mod.OpenAIBackendConfig(
            api_key_env="OPENAI_API_KEY", model="whisper-1"
        ),
    )
    monkeypatch.setattr(
        "murmuro.secrets.get",
        lambda name, env_var=None: "sk-from-keychain",
    )
    transcriber = build(cfg)
    assert isinstance(transcriber, OpenAICompatible)
    assert transcriber.base_url == "https://api.openai.com/v1"
    assert transcriber.model == "whisper-1"
    assert transcriber.api_key == "sk-from-keychain"


def test_factory_raises_when_api_key_missing(monkeypatch):
    cfg = config_mod.Config(
        backend="openai",
        openai=config_mod.OpenAIBackendConfig(api_key_env="OPENAI_API_KEY"),
    )
    monkeypatch.setattr("murmuro.secrets.get", lambda name, env_var=None: None)
    with pytest.raises(RuntimeError, match="no API key found"):
        build(cfg)
