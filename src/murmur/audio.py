"""Microphone capture as 16 kHz mono float32 PCM."""
from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
CHANNELS = 1
DTYPE = "float32"

# Tuning constants for the live mic-volume readout consumed by the HUD.
#
# ``_LEVEL_RMS_REFERENCE`` is the raw float32 RMS we treat as "loud" — the
# value at which the smoothed level saturates at 1.0. 0.1 is a reasonable
# constant for a typical built-in mic at conversational distance: normal
# speech RMS lands around 0.03–0.07 (which maps to 0.3–0.7), while shouting
# / clipping pushes well past 0.1 and gets clamped. Tune this if the dots
# feel too sleepy or too jumpy in real-world use.
_LEVEL_RMS_REFERENCE = 0.1
# Exponential-smoothing factor: higher = more reactive, lower = smoother.
# 0.3 keeps the dots lively without strobing on every consonant.
_LEVEL_ALPHA = 0.3


class Recorder:
    """Start/stop microphone capture; returns concatenated samples on stop."""

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        # Live, smoothed volume level in [0.0, 1.0]. Plain float attribute:
        # CPython's GIL makes single-attribute load/store atomic for floats,
        # so the HUD can read this from the Qt main thread while the audio
        # callback writes from PortAudio's thread without locking. Keeping
        # audio.py framework-free (no Qt signals) preserves the architectural
        # stance documented in docs/adr/0002.
        self.current_level: float = 0.0

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        with self._lock:
            self._chunks.append(indata.copy())
        # Compute RMS over this chunk and exponentially smooth into the
        # public level. We do this outside the lock — the lock only guards
        # the chunk list, and current_level is a single-float attribute that
        # only this thread writes to while recording is active.
        # ``indata`` is float32 in roughly [-1, 1]; squaring and meaning is
        # cheap and numerically stable for the chunk sizes we see (~30 ms).
        # Cast to float64 for the squaring step so we don't accumulate
        # round-off when summing float32 squares over a chunk.
        samples = np.asarray(indata, dtype=np.float64).ravel()
        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
        normalised = min(1.0, max(0.0, rms / _LEVEL_RMS_REFERENCE))
        self.current_level = (
            _LEVEL_ALPHA * normalised + (1.0 - _LEVEL_ALPHA) * self.current_level
        )

    def start(self) -> None:
        if self._stream is not None:
            return
        self._chunks = []
        # Reset on start as well as stop — defence in depth against a stale
        # reading leaking across sessions if stop() ever short-circuits.
        self.current_level = 0.0
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        # Reset unconditionally so the HUD doesn't render a stale "loud"
        # reading the next time it polls before recording resumes — even
        # in the no-stream short-circuit branch.
        self.current_level = 0.0
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
