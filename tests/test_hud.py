"""Smoke tests for the recording HUD widget.

We can't visually inspect Qt in headless CI, but we can verify the widget
constructs, can be shown/hidden, and the timer wiring is intact. The
elapsed-time formatter is pulled out as a pure function so we can pin its
edge cases (the 60.0s flip in particular) without spinning the event loop.
"""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

# Force offscreen QPA so the test passes on CI without a display server.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from murmur.hud import RecordingHUD, _format_elapsed  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_hud_constructs(qapp):
    hud = RecordingHUD()
    assert hud.width() == RecordingHUD.WIDTH
    assert hud.height() == RecordingHUD.HEIGHT


def test_hud_bounds_are_compact_pill(qapp):
    """The redesigned HUD is a 100x24 pill — half the previous footprint."""
    hud = RecordingHUD()
    assert hud.width() == 100
    assert hud.height() == 24


def test_hud_show_starts_timer(qapp):
    hud = RecordingHUD()
    assert not hud._timer.isActive()
    hud.show_at_bottom_center()
    assert hud._timer.isActive()
    hud.hide()
    assert not hud._timer.isActive()


def test_hud_paint_does_not_crash(qapp):
    """Smoke-render to a QPixmap — verifies the paintEvent doesn't blow up
    on the new geometry / dot cluster layout. We deliberately don't assert
    on what was drawn (too brittle); only that it didn't crash."""
    hud = RecordingHUD()
    hud.show_at_bottom_center()
    hud._tick()  # exercise the repaint nudge path
    pixmap = QPixmap(hud.size())
    hud.render(pixmap)
    hud.hide()


def test_hud_lands_in_lower_half_of_screen(qapp):
    """Sanity-check the new bottom-center placement: y should be below
    the screen's vertical midpoint, not above it."""
    from PySide6.QtWidgets import QApplication
    hud = RecordingHUD()
    hud.show_at_bottom_center()
    screen = QApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        midpoint = geo.top() + geo.height() // 2
        assert hud.y() >= midpoint, (
            f"HUD at y={hud.y()} should be in lower half of screen "
            f"(midpoint={midpoint})"
        )
    hud.hide()


# ─────────────────────────────────────────────────────────────────────────────
# _format_elapsed: pure function, exercise the seconds <-> minutes flip.
# ─────────────────────────────────────────────────────────────────────────────


def test_format_elapsed_zero():
    assert _format_elapsed(0.0) == "0.0s"


def test_format_elapsed_decimal_seconds():
    assert _format_elapsed(12.3) == "12.3s"


def test_format_elapsed_truncates_does_not_round():
    # 12.39 must render as 12.3, not 12.4 — we truncate so the displayed
    # tenths digit never gets ahead of the real elapsed time.
    assert _format_elapsed(12.39) == "12.3s"


def test_format_elapsed_just_below_one_minute():
    assert _format_elapsed(59.9) == "59.9s"


def test_format_elapsed_just_below_one_minute_truncates():
    # 59.99 still belongs to the seconds bucket because we truncate.
    assert _format_elapsed(59.99) == "59.9s"


def test_format_elapsed_exactly_one_minute_flips():
    """At exactly 60.0 the format flips to whole-second 'Nm Ms'."""
    assert _format_elapsed(60.0) == "1m 0s"


def test_format_elapsed_under_two_minutes():
    assert _format_elapsed(119.9) == "1m 59s"


def test_format_elapsed_exactly_two_minutes():
    assert _format_elapsed(120.0) == "2m 0s"


def test_format_elapsed_negative_clamps_to_zero():
    """Defensive: monotonic clock skew shouldn't paint a negative timer."""
    assert _format_elapsed(-1.0) == "0.0s"
