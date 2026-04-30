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


# ─────────────────────────────────────────────────────────────────────────────
# Volume-reactive dots — exercise the level→radius/alpha mapping.
# ─────────────────────────────────────────────────────────────────────────────


def _render_to_pixmap(hud: RecordingHUD) -> QPixmap:
    pixmap = QPixmap(hud.size())
    pixmap.fill()  # white background so we can find the dot pixels
    hud.render(pixmap)
    return pixmap


def test_hud_silent_baseline_matches_static_design(qapp):
    """At level=0 the dots must match #14's static look (2 px, ~30 % alpha)
    so the redesign isn't visually regressed."""
    hud = RecordingHUD(level_provider=lambda: 0.0)
    # Read directly from the geometry constants to pin the contract; the
    # paintEvent uses these same constants on the level=0 branch.
    assert hud._DOT_BASELINE_DIAMETER == 2
    assert hud._DOT_BASELINE_ALPHA == 77
    # Smoke render — must not crash and must paint a baseline frame.
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)
    hud.hide()


def test_hud_peak_level_reaches_peak_geometry(qapp):
    """At level=1.0 dots are 6 px diameter / fully opaque per the issue."""
    hud = RecordingHUD(level_provider=lambda: 1.0)
    assert hud._DOT_PEAK_DIAMETER == 6
    assert hud._DOT_PEAK_ALPHA == 255
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)
    hud.hide()


def test_hud_intermediate_level_renders_without_crash(qapp):
    """Mid-range level produces an intermediate radius/alpha; we don't try
    to read pixels here (too brittle across Qt versions) — we just confirm
    the paint path completes for a non-edge level."""
    hud = RecordingHUD(level_provider=lambda: 0.5)
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)
    hud.hide()


def test_hud_no_level_provider_does_not_crash(qapp):
    """Defensive: the HUD must render even without a level source — e.g.
    when constructed in a test or before the recorder is wired up."""
    hud = RecordingHUD()  # no provider
    assert hud._current_level() == 0.0
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)
    hud.hide()


def test_hud_level_provider_exception_is_swallowed(qapp):
    """A broken provider must degrade gracefully to baseline — never crash
    the HUD repaint."""
    def boom() -> float:
        raise RuntimeError("audio thread is dead")

    hud = RecordingHUD(level_provider=boom)
    assert hud._current_level() == 0.0  # falls back to baseline
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)
    hud.hide()


def test_hud_level_clamped_to_unit_interval(qapp):
    """Out-of-range levels (negative, > 1) clamp before driving the paint."""
    hud_low = RecordingHUD(level_provider=lambda: -2.5)
    hud_high = RecordingHUD(level_provider=lambda: 99.0)
    assert hud_low._current_level() == 0.0
    assert hud_high._current_level() == 1.0


def test_hud_set_level_provider_late_binds(qapp):
    """The setter exists so the HUD can be constructed before the recorder
    is available without forcing a re-instantiation."""
    hud = RecordingHUD()
    hud.set_level_provider(lambda: 0.7)
    assert hud._current_level() == pytest.approx(0.7)
    hud.set_level_provider(None)
    assert hud._current_level() == 0.0


def test_hud_timer_runs_at_30hz(qapp):
    """30 Hz polling for smooth volume-reactive animation."""
    hud = RecordingHUD()
    assert hud._timer.interval() == 33
