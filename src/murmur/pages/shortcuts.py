"""Shortcuts page: pick the push-to-talk hotkey.

Single row for now (push-to-talk). Hands-free toggle and "Add another"
land in Phase 3 — they share this page so the layout already accommodates
multiple rows via a vertical box.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import config as config_mod
from ..hotkey_recorder import HotkeyRecorder
from ..key_probe import KeyProbe
from ..ui.theme import card, hint_label, section_label


class ShortcutsPage(QWidget):
    """Hotkey configuration."""

    preferences_changed = Signal()

    def __init__(self, cfg: config_mod.Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        layout.addWidget(section_label("Push to talk"))
        ptt_card = card()
        ptt_layout = QHBoxLayout(ptt_card)
        ptt_layout.setContentsMargins(18, 14, 18, 14)
        desc = QLabel("Hold this key while you talk; release to transcribe.")
        desc.setProperty("dim", True)
        ptt_layout.addWidget(desc, 1)
        self.hotkey_recorder = HotkeyRecorder(cfg.hotkey)
        # Re-emit through the page's preferences_changed bus so MainWindow
        # actually persists the new hotkey. Without this, the recorder
        # silently updates its own state and the next launch reads the
        # old value from disk.
        self.hotkey_recorder.value_changed.connect(
            lambda _spec: self.preferences_changed.emit()
        )
        ptt_layout.addWidget(self.hotkey_recorder)
        layout.addWidget(ptt_card)

        layout.addWidget(hint_label(
            "Click Record, then press the key (or combo) you want as your "
            "push-to-talk shortcut. Esc cancels."
        ))

        layout.addSpacing(10)
        layout.addWidget(section_label("Test any key"))
        probe_card = card()
        probe_layout = QVBoxLayout(probe_card)
        probe_layout.setContentsMargins(18, 14, 18, 14)
        probe_layout.setSpacing(10)
        probe_layout.addWidget(hint_label(
            "Not sure if a key is bindable on your keyboard? Click below and "
            "press it — Murmur shows what it sees."
        ))
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
