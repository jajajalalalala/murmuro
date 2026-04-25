"""Smoke tests for the recording HUD widget.

We can't visually inspect Qt in headless CI, but we can verify the widget
constructs, can be shown/hidden, and the timer wiring is intact.
"""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

# Force offscreen QPA so the test passes on CI without a display server.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from murmur.hud import RecordingHUD  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_hud_constructs(qapp):
    hud = RecordingHUD()
    assert hud.width() == RecordingHUD.WIDTH
    assert hud.height() == RecordingHUD.HEIGHT


def test_hud_show_starts_timer(qapp):
    hud = RecordingHUD()
    assert not hud._timer.isActive()
    hud.show_at_top_center()
    assert hud._timer.isActive()
    hud.hide()
    assert not hud._timer.isActive()


def test_hud_paint_does_not_crash(qapp):
    hud = RecordingHUD()
    hud.show_at_top_center()
    # Trigger a paint via the timer's tick handler.
    hud._tick()
    hud.repaint()
    hud.hide()
