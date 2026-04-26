"""Theme module: applying it should produce a non-empty stylesheet and
swap the QPalette accent color, regardless of system theme."""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from murmur.ui.theme import (  # noqa: E402
    ACCENT,
    DARK,
    LIGHT,
    apply_theme,
    card,
    hint_label,
    primary_button,
    section_label,
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication(sys.argv)


def test_apply_theme_light_sets_accent_highlight(qapp):
    apply_theme(qapp, palette=LIGHT)
    highlight = qapp.palette().color(QPalette.ColorRole.Highlight)
    assert highlight.name().lower() == ACCENT.lower()
    assert qapp.styleSheet()  # non-empty stylesheet was installed


def test_apply_theme_dark_uses_dark_surface(qapp):
    apply_theme(qapp, palette=DARK)
    base = qapp.palette().color(QPalette.ColorRole.Base)
    assert base.name().lower() == DARK.surface.lower()


def test_helpers_set_property_flags(qapp):
    apply_theme(qapp, palette=LIGHT)
    assert card().property("card") is True
    assert section_label("X").property("section") is True
    assert hint_label("h").property("hint") is True
    assert primary_button("Go").property("primary") is True


def test_force_theme_env_var(qapp, monkeypatch):
    monkeypatch.setenv("MURMUR_FORCE_THEME", "dark")
    p = apply_theme(qapp)
    assert p.name == "dark"
    monkeypatch.setenv("MURMUR_FORCE_THEME", "light")
    p = apply_theme(qapp)
    assert p.name == "light"
