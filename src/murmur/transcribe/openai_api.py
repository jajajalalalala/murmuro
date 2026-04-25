"""OpenAI Whisper API transcription backend."""
from __future__ import annotations

import io
import wave

import numpy as np


class OpenAIWhisper:
    def __init__(self, api_key: str, model: str = "whisper-1") -> None:
        if not api_key:
            raise ValueError("OpenAI API key is empty")
        self.api_key = api_key
        self.model = model
        self._client = None

    def _client_lazy(self):
        if self._client is not None:
            return self._client
        from openai import OpenAI

        self._client = OpenAI(api_key=self.api_key)
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
