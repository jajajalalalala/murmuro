"""OpenAI-compatible cloud transcription backend.

A single class that targets any OpenAI-compatible ``/audio/transcriptions``
endpoint. Providers (OpenAI, Groq, DeepSeek, MiniMax, user-added custom
endpoints) differ only in ``base_url``, ``api_key``, and ``model`` — hence
the constructor tuple. See
``docs/adr/0002-single-openai-compatible-transcriber.md``.
"""
from __future__ import annotations

import io
import wave

import numpy as np


class OpenAICompatible:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("API key is empty")
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self._client = None

    def _client_lazy(self):
        if self._client is not None:
            return self._client
        from openai import OpenAI

        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def transcribe(
        self,
        pcm: np.ndarray,
        sample_rate: int,
        language: str | None = None,
    ) -> str:
        if pcm.size == 0:
            return ""
        wav_bytes = _pcm_to_wav_bytes(pcm, sample_rate)
        buf = io.BytesIO(wav_bytes)
        buf.name = "audio.wav"
        client = self._client_lazy()
        kwargs = {"model": self.model, "file": buf}
        if language and language != "auto":
            kwargs["language"] = language
        resp = client.audio.transcriptions.create(**kwargs)
        return (resp.text or "").strip()


def probe_connection(
    base_url: str,
    api_key: str,
    model: str,
    *,
    sample_rate: int = 16_000,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """Send a 1-second silence clip to the endpoint as a connectivity check.

    Used by the Models page's **Test connection** button. Surfaces the
    most common failure modes (missing key, wrong base URL, expired
    key, model not allowed on this account) before the user discovers
    them on a real push-to-talk.

    Returns ``(ok, message)``. On success ``message`` is a short
    confirmation including the round-trip latency. On failure it's a
    one-line, user-readable explanation — no stack traces, no
    upstream-internal jargon.
    """
    import time

    if not api_key:
        return False, "API key is empty. Set the env var on Models, then retry."

    silence = np.zeros(sample_rate, dtype=np.float32)
    backend = OpenAICompatible(base_url=base_url, api_key=api_key, model=model)
    started = time.perf_counter()
    try:
        backend.transcribe(silence, sample_rate)
    except Exception as e:  # noqa: BLE001
        return False, _humanize_probe_error(e)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return True, f"Connected in {elapsed_ms} ms · {model} on {base_url}"


def _humanize_probe_error(exc: Exception) -> str:
    """Map ``openai.APIError`` and friends to a one-line user message."""
    name = type(exc).__name__
    msg = str(exc).strip() or name
    # The OpenAI SDK raises specific subclasses we can recognize by
    # name without importing them (which would crash if the package
    # ever splits or renames). Fall through to a generic phrasing for
    # anything else.
    if "AuthenticationError" in name:
        return "API key was rejected. Check the value of the env var on Models."
    if "RateLimitError" in name:
        return "Rate-limited by the provider. Wait a moment and retry."
    if "APIConnectionError" in name or "ConnectionError" in name:
        return "Couldn't reach the endpoint. Check your network or the base URL."
    if "NotFoundError" in name:
        return f"Model not available on this endpoint: {msg}"
    return f"{name}: {msg}"


def _pcm_to_wav_bytes(pcm: np.ndarray, sample_rate: int) -> bytes:
    pcm_int16 = np.clip(pcm * 32768.0, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm_int16.tobytes())
    return buf.getvalue()
