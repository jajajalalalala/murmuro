"""Local Whisper transcription via faster-whisper (CTranslate2)."""
from __future__ import annotations

import numpy as np


class LocalWhisper:
    def __init__(
        self,
        model: str = "base",
        device: str = "auto",
        compute_type: str = "int8",
        download_root: str | None = None,
    ) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        # ``None`` lets faster-whisper / huggingface_hub fall back to its
        # default cache location. The factory resolves Murmuro's private
        # path (under platformdirs.user_data_dir) before we get here, so
        # this code path stays simple.
        self.download_root = download_root
        self._model = None  # lazy-loaded

    def _load(self):
        if self._model is not None:
            return self._model
        # Imported here so the module is importable without faster-whisper installed.
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            download_root=self.download_root,
        )
        return self._model

    def transcribe(
        self,
        pcm: np.ndarray,
        sample_rate: int,
        language: str | None = None,
    ) -> str:
        if pcm.size == 0:
            return ""
        if sample_rate != 16_000:
            raise ValueError(f"LocalWhisper expects 16 kHz audio, got {sample_rate}")
        model = self._load()
        lang = None if language in (None, "", "auto") else language
        segments, _info = model.transcribe(
            pcm,
            language=lang,
            vad_filter=True,
            beam_size=5,
        )
        return "".join(seg.text for seg in segments).strip()
