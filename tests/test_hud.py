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
    """The redesigned HUD is an 88x24 pill — sized to fit the worst-case
    timer ("1m 23s") with the bar cluster, so content reads close to
    centered rather than left-crowded with empty space on the right."""
    hud = RecordingHUD()
    assert hud.width() == 88
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
# 5-bar staggered waveform — ring-buffer + per-slot height/alpha mapping.
# ─────────────────────────────────────────────────────────────────────────────


def _render_to_pixmap(hud: RecordingHUD) -> QPixmap:
    pixmap = QPixmap(hud.size())
    pixmap.fill()  # white background so we can find the bar pixels
    hud.render(pixmap)
    return pixmap


def _slot_height(slot_level: float) -> int:
    """Mirror the height ramp from RecordingHUD.paintEvent so tests can
    pin the exact per-slot geometry without inspecting pixels."""
    return RecordingHUD._BAR_BASELINE_HEIGHT + int(
        (RecordingHUD._BAR_PEAK_HEIGHT - RecordingHUD._BAR_BASELINE_HEIGHT)
        * slot_level
    )


def _slot_alpha(slot_level: float) -> int:
    return RecordingHUD._BAR_BASELINE_ALPHA + int(
        (RecordingHUD._BAR_PEAK_ALPHA - RecordingHUD._BAR_BASELINE_ALPHA)
        * slot_level
    )


def test_hud_geometry_constants_match_visual_contract(qapp):
    """Pin the public visual contract from #31: 5 bars × 2 px wide × 3 px
    gap, height 2 → 18 px, alpha 127 → 255, pure white."""
    assert RecordingHUD._BAR_COUNT == 5
    assert RecordingHUD._BAR_WIDTH == 2
    assert RecordingHUD._BAR_GAP == 3
    assert RecordingHUD._BAR_BASELINE_HEIGHT == 2
    assert RecordingHUD._BAR_PEAK_HEIGHT == 18
    assert RecordingHUD._BAR_BASELINE_ALPHA == 127
    assert RecordingHUD._BAR_PEAK_ALPHA == 255
    assert RecordingHUD._BAR_RGB == (255, 255, 255)
    # 5 × 2 + 4 × 3 = 22 px footprint.
    assert RecordingHUD._BAR_CLUSTER_WIDTH == 22


def test_hud_silent_baseline_after_buffer_fills(qapp):
    """level=0.0 sustained for ≥ 5 ticks → every slot reads the silent
    baseline (2 px tall, alpha 127)."""
    hud = RecordingHUD(level_provider=lambda: 0.0)
    for _ in range(RecordingHUD._BAR_COUNT):
        hud._tick()
    assert list(hud._levels) == [0.0] * RecordingHUD._BAR_COUNT
    for level in hud._levels:
        assert _slot_height(level) == 2
        assert _slot_alpha(level) == 127
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)
    hud.hide()


def test_hud_peak_level_after_buffer_fills(qapp):
    """level=1.0 sustained for ≥ 5 ticks → every slot at peak
    (18 px tall, alpha 255)."""
    hud = RecordingHUD(level_provider=lambda: 1.0)
    for _ in range(RecordingHUD._BAR_COUNT):
        hud._tick()
    assert list(hud._levels) == [1.0] * RecordingHUD._BAR_COUNT
    for level in hud._levels:
        assert _slot_height(level) == 18
        assert _slot_alpha(level) == 255
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)
    hud.hide()


def test_hud_stagger_rightmost_is_newest(qapp):
    """Feed [0.2, 0.4, 0.6, 0.8, 1.0] over 5 consecutive ticks. The
    rightmost slot must be the most recent sample (1.0) and the leftmost
    the oldest still in the buffer (0.2). This is the visible
    left-to-right travel of voice peaks."""
    feed = [0.2, 0.4, 0.6, 0.8, 1.0]
    pointer = {"i": 0}

    def provider() -> float:
        v = feed[pointer["i"]]
        pointer["i"] += 1
        return v

    hud = RecordingHUD(level_provider=provider)
    for _ in range(len(feed)):
        hud._tick()
    slots = list(hud._levels)
    assert slots == feed  # leftmost = oldest, rightmost = newest
    assert slots[0] == pytest.approx(0.2)
    assert slots[-1] == pytest.approx(1.0)


def test_hud_intermediate_level_renders_without_crash(qapp):
    """Mid-range level produces an intermediate height/alpha; we don't try
    to read pixels here (too brittle across Qt versions) — we just confirm
    the paint path completes for a non-edge level."""
    hud = RecordingHUD(level_provider=lambda: 0.5)
    for _ in range(RecordingHUD._BAR_COUNT):
        hud._tick()
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)
    hud.hide()


def test_hud_no_level_provider_stays_at_baseline(qapp):
    """Defensive: with no provider every tick pushes 0.0, so all bars
    stay at the silent baseline. Must never crash."""
    hud = RecordingHUD()  # no provider
    assert hud._current_level() == 0.0
    for _ in range(RecordingHUD._BAR_COUNT):
        hud._tick()
    assert list(hud._levels) == [0.0] * RecordingHUD._BAR_COUNT
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)
    hud.hide()


def test_hud_level_provider_exception_is_swallowed(qapp):
    """A broken provider must degrade gracefully to the silent baseline —
    every tick pushes 0.0 and the paint path keeps running."""
    def boom() -> float:
        raise RuntimeError("audio thread is dead")

    hud = RecordingHUD(level_provider=boom)
    assert hud._current_level() == 0.0  # falls back to baseline
    for _ in range(RecordingHUD._BAR_COUNT):
        hud._tick()
    assert list(hud._levels) == [0.0] * RecordingHUD._BAR_COUNT
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)
    hud.hide()


def test_hud_fresh_construction_renders_at_baseline(qapp):
    """A freshly-constructed HUD with zero ticks renders all 5 bars at
    the silent baseline because the deque is pre-populated with zeros."""
    hud = RecordingHUD(level_provider=lambda: 1.0)
    # No ticks yet: the buffer must already hold 5 zeros.
    assert list(hud._levels) == [0.0] * RecordingHUD._BAR_COUNT
    hud.show_at_bottom_center()
    _render_to_pixmap(hud)  # must not crash before any sample arrives
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
    """30 Hz polling for smooth waveform animation — also sets the stagger
    speed (5 slots × 33 ms ≈ 165 ms per traversal)."""
    hud = RecordingHUD()
    assert hud._timer.interval() == 33
