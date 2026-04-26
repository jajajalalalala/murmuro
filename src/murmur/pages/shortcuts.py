"""Shortcuts page: pick the push-to-talk hotkey.

Single row for now (push-to-talk). Hands-free toggle and "Add another"
land in Phase 3 — they share this page so the layout already accommodates
multiple rows via a vertical box.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import config as config_mod
from ..hotkey_recorder import HotkeyRecorder
from ..key_probe import KeyProbe


class ShortcutsPage(QWidget):
    """Hotkey configuration."""

    preferences_changed = Signal()

    def __init__(self, cfg: config_mod.Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(_section("Push to talk"))
        ptt_card = _card()
        ptt_layout = QHBoxLayout(ptt_card)
        ptt_layout.setContentsMargins(16, 12, 16, 12)
        desc = QLabel("Hold this key while you talk; release to transcribe.")
        desc.setStyleSheet("color: palette(mid);")
        ptt_layout.addWidget(desc, 1)
        self.hotkey_recorder = HotkeyRecorder(cfg.hotkey)
        ptt_layout.addWidget(self.hotkey_recorder)
        layout.addWidget(ptt_card)

        hint = QLabel(
            "Click Record, then press the key (or combo) you want as your "
            "push-to-talk shortcut. Esc cancels."
        )
        hint.setStyleSheet("color: palette(mid); font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addSpacing(8)
        layout.addWidget(_section("Test any key"))
        probe_card = _card()
        probe_layout = QVBoxLayout(probe_card)
        probe_layout.setContentsMargins(16, 12, 16, 12)
        probe_layout.setSpacing(8)
        probe_intro = QLabel(
            "Not sure if a key is bindable on your keyboard? Click below and "
            "press it — Murmur shows what it sees."
        )
        probe_intro.setStyleSheet("color: palette(mid); font-size: 11px;")
        probe_intro.setWordWrap(True)
        probe_layout.addWidget(probe_intro)
        self.key_probe = KeyProbe()
        probe_layout.addWidget(self.key_probe)
        layout.addWidget(probe_card)

        layout.addStretch(1)

    # ------------------------------------------------------------------

    def set_config(self, cfg: config_mod.Config) -> None:
        self._cfg = cfg
        self.hotkey_recorder.set_value(cfg.hotkey)

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        # Empty value (user opened recorder, never pressed anything) keeps
        # the previous hotkey rather than clearing it to nothing.
        cfg.hotkey = self.hotkey_recorder.value() or self._cfg.hotkey
        return cfg


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: 600; font-size: 13px;")
    return label


def _card() -> QFrame:
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    return frame
