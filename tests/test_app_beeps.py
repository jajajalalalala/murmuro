"""MurmuroApp wires cue tones into the press/release path.

Verifies the on/off behavior driven by Config.play_beeps without touching
the real audio output (which CI runners don't have anyway).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from murmuro.app import MurmuroApp
from murmuro.config import Config


def _silent_recorder() -> MagicMock:
    rec = MagicMock()
    rec.stop.return_value = MagicMock(size=0)  # tiny buffer → skipped
    return rec


def test_press_plays_start_tone_when_enabled():
    cfg = Config(play_beeps=True)
    with (
        patch("murmuro.app.Recorder", return_value=_silent_recorder()),
        patch("murmuro.app.play_start") as start,
        patch("murmuro.app.play_stop") as stop,
    ):
        app = MurmuroApp(cfg=cfg)
        app._on_press()
    assert start.called, "expected start beep on press"
    assert not stop.called


def test_release_plays_stop_tone_when_enabled():
    cfg = Config(play_beeps=True)
    with (
        patch("murmuro.app.Recorder", return_value=_silent_recorder()),
        patch("murmuro.app.play_start"),
        patch("murmuro.app.play_stop") as stop,
    ):
        app = MurmuroApp(cfg=cfg)
        app._on_press()
        app._on_release()
    assert stop.called, "expected stop beep on release"


def test_beeps_skipped_when_disabled():
    """play_beeps=False is the user opt-out — neither tone should fire."""
    cfg = Config(play_beeps=False)
    with (
        patch("murmuro.app.Recorder", return_value=_silent_recorder()),
        patch("murmuro.app.play_start") as start,
        patch("murmuro.app.play_stop") as stop,
    ):
        app = MurmuroApp(cfg=cfg)
        app._on_press()
        app._on_release()
    assert not start.called
    assert not stop.called


def test_default_config_has_beeps_enabled():
    """Default-on so the user gets eyes-free confirmation out of the box."""
    assert Config().play_beeps is True
