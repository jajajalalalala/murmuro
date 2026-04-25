"""Microphone capture as 16 kHz mono float32 PCM."""
from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
CHANNELS = 1
DTYPE = "float32"


class Recorder:
    """Start/stop microphone capture; returns concatenated samples on stop."""

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        with self._lock:
            self._chunks.append(indata.copy())

    def start(self) -> None:
        if self._stream is not None:
            return
        self._chunks = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks, axis=0).flatten()
        return audio.astype(np.float32, copy=False)

    @property
    def is_recording(self) -> bool:
        return self._stream is not None
