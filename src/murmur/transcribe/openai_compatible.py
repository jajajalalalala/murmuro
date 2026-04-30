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


def _pcm_to_wav_bytes(pcm: np.ndarray, sample_rate: int) -> bytes:
    pcm_int16 = np.clip(pcm * 32768.0, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm_int16.tobytes())
    return buf.getvalue()
