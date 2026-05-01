"""Tiny synthesized cue tones played around the recording lifecycle.

Two short sine pings: a higher-pitched one when recording starts, a
lower-pitched one when it ends. They give the user audible confirmation
of the state machine without an on-screen flicker — useful when the HUD
is hidden, the user is in fullscreen, or attention is on the keyboard.

Generated in-process with numpy + sounddevice (already used by the
recorder) so we don't shell out to ``afplay`` or ship a wav file. Each
tone fires from a daemon thread so the audio stream stop/start in the
push-to-talk hot path isn't held up by the playback duration.

Honours ``Config.play_beeps``; the caller is responsible for checking
that flag before invoking these helpers (kept this module pure of
config so it stays trivially mockable in tests).
"""
from __future__ import annotations

import threading

import numpy as np

from ._logging import get_logger

_log = get_logger("sounds")

_SAMPLE_RATE = 44_100  # output device rate; 16k mic rate is independent
_FADE_MS = 8           # short cosine fade so the click on tone-edges is gone
_VOLUME = 0.18         # leave headroom — user might have system volume up


def _tone(frequency_hz: float, duration_ms: int) -> np.ndarray:
    """A single mono sine wave with cosine-shaped fade in/out."""
    n = int(_SAMPLE_RATE * duration_ms / 1000)
    t = np.arange(n, dtype=np.float32) / _SAMPLE_RATE
    wave = np.sin(2.0 * np.pi * frequency_hz * t, dtype=np.float32)

    fade_n = max(1, int(_SAMPLE_RATE * _FADE_MS / 1000))
    if fade_n * 2 < n:
        ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, fade_n, dtype=np.float32)))
        wave[:fade_n] *= ramp
        wave[-fade_n:] *= ramp[::-1]
    return (wave * _VOLUME).astype(np.float32, copy=False)


# Pre-rendered tones — generated once at module import. Cheap, but no point
# re-allocating two ~9 KB arrays on every push-to-talk press.
_START_TONE: np.ndarray = _tone(880.0, 120)   # A5, brief & bright
_END_TONE: np.ndarray = _tone(523.25, 160)    # C5, lower + slightly longer = "done"


def _play_async(samples: np.ndarray) -> None:
    """Fire-and-forget playback on a daemon thread.

    Failures (no output device, sounddevice misconfigured, sandboxed
    environment) are logged at debug level and swallowed — a missing
    cue tone must never break the actual recording flow.
    """
    def _run() -> None:
        try:
            import sounddevice as sd

            sd.play(samples, _SAMPLE_RATE, blocking=True)
        except Exception as exc:  # noqa: BLE001
            _log.debug("cue tone playback failed: %s", exc)

    threading.Thread(target=_run, name="murmuro-cue", daemon=True).start()


def play_start() -> None:
    """Higher-pitched ping signalling the recorder has just opened."""
    _play_async(_START_TONE)


def play_stop() -> None:
    """Lower-pitched ping signalling the recorder has closed."""
    _play_async(_END_TONE)


__all__ = ["play_start", "play_stop"]
