"""Recording cue tones — unit tests.

Real audio playback is mocked: CI runners (and most dev machines under
``QT_QPA_PLATFORM=offscreen``) have no usable output device, and we don't
want pytest making noise either way. We verify the helpers compose the
expected tone shape and that the public ``play_*`` calls dispatch a
playback thread without raising.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from murmur import sounds


def test_tones_have_distinct_pitches():
    """Start tone should be higher-pitched than the end tone — that's
    the whole point: rising = open, falling = close."""
    start_freq = float(_dominant_frequency(sounds._START_TONE))
    end_freq = float(_dominant_frequency(sounds._END_TONE))
    assert start_freq > end_freq, (start_freq, end_freq)


def test_tone_has_silent_endpoints():
    """The cosine fade-in/out should leave both edges near zero so we
    don't hear a click on every beep."""
    tone = sounds._tone(880.0, 100)
    assert abs(tone[0]) < 0.01
    assert abs(tone[-1]) < 0.01
    # but the body of the tone is not silent — the middle sample alone
    # might land on a sine zero-crossing, so check the peak of the
    # middle third instead.
    third = len(tone) // 3
    assert np.max(np.abs(tone[third:-third])) > 0.05


def test_tone_respects_duration_in_samples():
    tone = sounds._tone(440.0, 50)
    # 50 ms at 44.1 kHz = 2205 samples
    assert tone.shape == (2205,)
    assert tone.dtype == np.float32


def test_play_start_dispatches_thread_and_returns_immediately(monkeypatch):
    """Public API never blocks the caller. We swap sounddevice.play with
    a stub that records the call so the test doesn't touch real audio."""
    calls: list[tuple[int, int]] = []

    class _StubSD:
        @staticmethod
        def play(samples, rate, blocking=False):  # noqa: ARG004
            calls.append((len(samples), rate))

    # Replace the import inside the playback thread.
    import sys
    monkeypatch.setitem(sys.modules, "sounddevice", _StubSD)

    sounds.play_start()
    sounds.play_stop()

    # Both fire-and-forget threads should finish quickly; give them a
    # moment to run before we check what they recorded.
    deadline = time.monotonic() + 1.0
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(calls) == 2
    rates = {rate for _n, rate in calls}
    assert rates == {sounds._SAMPLE_RATE}


def test_play_swallows_playback_errors(monkeypatch):
    """A missing/broken output device must not propagate into the
    push-to-talk hot path."""
    class _BoomSD:
        @staticmethod
        def play(*_a, **_k):
            raise RuntimeError("no output device")

    import sys
    monkeypatch.setitem(sys.modules, "sounddevice", _BoomSD)

    # No exception — even though the worker thread will hit the error.
    sounds.play_start()
    # Give the daemon thread time to run + die.
    for _ in range(20):
        if threading.active_count() == 1:
            break
        time.sleep(0.01)


# ---- helpers -----------------------------------------------------------

def _dominant_frequency(samples: np.ndarray) -> float:
    """Crude FFT peak finder used to confirm the tone is at the freq we asked for."""
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / sounds._SAMPLE_RATE)
    return freqs[int(np.argmax(spectrum))]
