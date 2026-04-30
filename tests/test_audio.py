"""Tests for the live mic-volume readout exposed by ``Recorder``.

We don't open a real audio stream — that needs a device and isn't safe in
CI. Instead we drive ``_callback`` directly with synthetic chunks, which is
exactly what ``sounddevice`` does at runtime.
"""
from __future__ import annotations

import numpy as np
import pytest

from murmur.audio import SAMPLE_RATE, Recorder


def _chunk(amplitude: float, n: int = 480) -> np.ndarray:
    """A 30 ms-equivalent chunk of constant-amplitude samples (so RMS == |amp|)."""
    return np.full((n, 1), amplitude, dtype=np.float32)


def test_recorder_starts_with_zero_level():
    rec = Recorder()
    assert rec.current_level == 0.0


def test_silent_chunks_keep_level_at_zero():
    rec = Recorder()
    silent = np.zeros((480, 1), dtype=np.float32)
    for _ in range(5):
        rec._callback(silent, 480, None, None)
    assert rec.current_level == 0.0


def test_level_rises_monotonically_under_steady_input():
    """Feeding the same loud chunk repeatedly should drive ``current_level``
    monotonically upward (exponential approach to the steady-state value)."""
    rec = Recorder()
    loud = _chunk(0.1)  # raw RMS == 0.1 → normalised to 1.0
    levels = []
    for _ in range(10):
        rec._callback(loud, 480, None, None)
        levels.append(rec.current_level)
    # Strictly non-decreasing, and asymptotically near 1.0.
    for prev, curr in zip(levels, levels[1:], strict=False):
        assert curr >= prev - 1e-9
    assert levels[-1] > 0.9


def test_level_clamps_at_one_for_very_loud_input():
    rec = Recorder()
    blast = _chunk(1.0)  # raw RMS == 1.0, way above the 0.1 reference
    for _ in range(20):
        rec._callback(blast, 480, None, None)
    assert rec.current_level <= 1.0
    assert rec.current_level > 0.99


def test_typical_speech_lands_in_mid_range():
    """Sanity-check the normalisation constant: a moderate-amplitude signal
    should map into the 0.3–0.7 band the HUD treats as "speaking"."""
    rec = Recorder()
    speech = _chunk(0.05)  # raw RMS == 0.05 → normalised to 0.5
    # Run enough callbacks for the EWMA to converge.
    for _ in range(30):
        rec._callback(speech, 480, None, None)
    assert 0.3 <= rec.current_level <= 0.7


def test_smoothing_is_not_instantaneous():
    """The first loud chunk should land below the steady-state — proving
    the EWMA actually smooths instead of snapping."""
    rec = Recorder()
    rec._callback(_chunk(0.1), 480, None, None)
    # alpha = 0.3, prior = 0.0, normalised = 1.0 → first reading == 0.3
    assert rec.current_level == pytest.approx(0.3, abs=1e-6)


def test_stop_resets_level_unconditionally():
    """``stop()`` must zero ``current_level`` even on the no-stream
    short-circuit path so a stale value can't leak into the next session."""
    rec = Recorder()
    # Pretend the stream was running and the level was non-zero.
    rec.current_level = 0.7
    rec.stop()  # no stream open → still resets the level
    assert rec.current_level == 0.0


def test_start_resets_level(monkeypatch):
    """A fresh ``start()`` must zero the level so the previous session's
    last reading can't bleed into the next one."""
    rec = Recorder()
    rec.current_level = 0.85

    class _FakeStream:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("murmur.audio.sd.InputStream", _FakeStream)
    rec.start()
    assert rec.current_level == 0.0
    rec.stop()
    assert rec.current_level == 0.0


def test_sample_rate_attribute_unchanged():
    """Defensive: the public ``sample_rate`` attribute should still match
    the module constant — adding ``current_level`` mustn't shift other
    parts of the contract."""
    rec = Recorder()
    assert rec.sample_rate == SAMPLE_RATE
