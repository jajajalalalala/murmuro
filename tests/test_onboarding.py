"""Smoke tests for the first-run onboarding wizard (#20).

The wizard is a QDialog with a 4-step QStackedWidget. We don't try to
test the live audio capture in step 4 (that needs a real mic and is
covered by the existing app_paste_flow tests for the post-wizard
state); instead we exercise the navigation surface, the
``apply_to_config`` plumbing on each step, and the persistence the
wizard does on Skip / Finish.
"""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from murmuro import config as config_mod  # noqa: E402
from murmuro.onboarding import OnboardingWizard  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication(sys.argv)


def _make_cfg() -> config_mod.Config:
    return config_mod.Config(
        backend="local",
        hotkey="<right_alt>",
        local=config_mod.LocalBackendConfig(model=""),
    )


def test_wizard_starts_on_step_one(qapp):
    w = OnboardingWizard(_make_cfg(), save_config=lambda _c: None)
    assert w._stack.currentIndex() == 0
    # Header reflects step name.
    assert "Welcome" in w._header.text()


def test_next_advances_through_all_steps(qapp):
    w = OnboardingWizard(_make_cfg(), save_config=lambda _c: None)
    for expected in (1, 2, 3):
        w._on_next()
        assert w._stack.currentIndex() == expected
    # On the last step the next button becomes "Finish".
    assert w._next_btn.text() == "Finish"


def test_back_returns_to_previous_step(qapp):
    w = OnboardingWizard(_make_cfg(), save_config=lambda _c: None)
    w._on_next()  # → step 2
    w._on_next()  # → step 3
    w._on_back()
    assert w._stack.currentIndex() == 1


def test_skip_persists_onboarded_flag(qapp):
    """Skipping at any step still flips ``onboarded=True`` so the
    wizard doesn't re-fire next launch."""
    saved: list[config_mod.Config] = []
    w = OnboardingWizard(_make_cfg(), save_config=saved.append)
    w._on_skip()
    assert saved, "save_config was not called on skip"
    assert saved[-1].onboarded is True
    assert w.result().skipped is True


def test_finish_persists_picks_along_with_onboarded_flag(qapp):
    """Walking through all four steps and finishing should land the
    selected model + hotkey on the saved config along with
    ``onboarded=True``."""
    saved: list[config_mod.Config] = []
    w = OnboardingWizard(_make_cfg(), save_config=saved.append)
    # Pick a non-default model on step 2.
    idx = w._model._combo.findData("tiny.en")
    if idx >= 0:
        w._model._combo.setCurrentIndex(idx)
    # Step through to the end and finish.
    for _ in range(3):
        w._on_next()
    w._on_next()  # last call triggers _finish()
    assert saved, "save_config was not called on finish"
    last = saved[-1]
    assert last.onboarded is True
    assert last.local.model == "tiny.en"
    assert w.result().completed is True
    assert w.result().skipped is False
