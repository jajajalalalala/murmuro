"""Home page: at-a-glance state, recent transcripts, global preferences.

The page is a passive view: it owns no transcription state of its own.
The main window pushes state-change events into ``set_state()`` and
appended transcripts into ``add_transcript()``. The toggles emit signals
that the main window forwards to the Config save path.
"""
from __future__ import annotations

from datetime import datetime

import pyperclip
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import config as config_mod
from ..app import State
from ..ui.theme import (
    STATE_BUSY,
    STATE_IDLE,
    STATE_RECORDING,
    card,
    hint_label,
    section_label,
)

_STATE_LABELS = {
    State.IDLE: ("Idle", STATE_IDLE),
    State.RECORDING: ("Recording", STATE_RECORDING),
    State.TRANSCRIBING: ("Transcribing", STATE_BUSY),
}

# Curated UI list — same set as the previous settings dialog so users keep
# the dropdown they're used to. The TOML still accepts arbitrary codes.
LANGUAGES = [
    ("auto", "Auto-detect"),
    ("en", "English"),
    ("zh", "Chinese"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
]


class HomePage(QWidget):
    """Status + recent transcripts + 'general' preferences."""

    # Emitted whenever the user flips a toggle or picks a language; the
    # main window persists the change.
    preferences_changed = Signal()

    MAX_TRANSCRIPTS = 5

    def __init__(self, cfg: config_mod.Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        # --- Status card ----------------------------------------------
        status_card = card()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(18, 14, 18, 14)
        status_layout.setSpacing(8)

        self._state_dot = QLabel()
        self._state_dot.setFixedSize(14, 14)
        self._state_text = QLabel("Idle")
        self._state_text.setStyleSheet("font-size: 20px; font-weight: 700;")
        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        status_row.addWidget(self._state_dot)
        status_row.addWidget(self._state_text)
        status_row.addStretch(1)
        status_layout.addLayout(status_row)

        self._summary = QLabel()
        self._summary.setProperty("dim", True)
        status_layout.addWidget(self._summary)
        layout.addWidget(status_card)

        # --- Recent transcripts ----------------------------------------
        layout.addWidget(section_label("Recent transcripts"))
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        # Word-wrap long transcripts onto multiple lines so the user
        # never has to scroll horizontally to read what they said.
        self._list.setWordWrap(True)
        self._list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Cap the list height so it doesn't balloon into a giant empty
        # block when there are no transcripts yet — when entries arrive
        # the list grows up to this max and then scrolls vertically.
        self._list.setMinimumHeight(120)
        self._list.setMaximumHeight(280)
        self._list.itemActivated.connect(self._on_transcript_activated)
        layout.addWidget(self._list)
        layout.addWidget(hint_label(
            "Each entry is timestamped. Double-click a row to copy it back "
            "to the clipboard."
        ))

        # --- Preferences -----------------------------------------------
        layout.addWidget(section_label("Preferences"))
        prefs_card = card()
        prefs = QFormLayout(prefs_card)
        prefs.setContentsMargins(18, 14, 18, 14)
        prefs.setHorizontalSpacing(16)
        prefs.setVerticalSpacing(10)

        self.auto_paste = QCheckBox("Auto-paste at cursor (uncheck = clipboard only)")
        self.auto_paste.setChecked(cfg.auto_paste)
        self.auto_paste.toggled.connect(lambda _: self.preferences_changed.emit())
        prefs.addRow("", self.auto_paste)

        self.show_hud = QCheckBox("Show recording HUD")
        self.show_hud.setChecked(cfg.show_hud)
        self.show_hud.toggled.connect(lambda _: self.preferences_changed.emit())
        prefs.addRow("", self.show_hud)

        self.language_combo = QComboBox()
        for code, label in LANGUAGES:
            self.language_combo.addItem(f"{label} ({code})", userData=code)
        idx = next(
            (i for i, (code, _) in enumerate(LANGUAGES) if code == cfg.language),
            0,
        )
        self.language_combo.setCurrentIndex(idx)
        self.language_combo.currentIndexChanged.connect(
            lambda _: self.preferences_changed.emit()
        )
        prefs.addRow("Language:", self.language_combo)
        layout.addWidget(prefs_card)

        self.set_state(State.IDLE)
        self._refresh_summary()

    # ------------------------------------------------------------------
    # Public hooks driven by the main window
    # ------------------------------------------------------------------

    def set_state(self, s: State) -> None:
        label, color = _STATE_LABELS.get(s, _STATE_LABELS[State.IDLE])
        self._state_text.setText(label)
        self._state_dot.setStyleSheet(
            f"background: {color}; border-radius: 7px;"
        )

    def set_config(self, cfg: config_mod.Config) -> None:
        """Sync the displayed preferences with a fresh Config."""
        self._cfg = cfg
        # Block signals so we don't echo a synthetic preferences_changed.
        for w in (self.auto_paste, self.show_hud, self.language_combo):
            w.blockSignals(True)
        self.auto_paste.setChecked(cfg.auto_paste)
        self.show_hud.setChecked(cfg.show_hud)
        idx = next(
            (i for i, (code, _) in enumerate(LANGUAGES) if code == cfg.language),
            0,
        )
        self.language_combo.setCurrentIndex(idx)
        for w in (self.auto_paste, self.show_hud, self.language_combo):
            w.blockSignals(False)
        self._refresh_summary()

    def add_transcript(self, text: str, when: datetime | None = None) -> None:
        if not text:
            return
        timestamp = (when or datetime.now()).strftime("%H:%M")
        # Two-line entry: bold-ish timestamp on top, full text below.
        # Word-wrap is enabled on the list so long transcripts span
        # multiple lines instead of triggering a horizontal scrollbar.
        item = QListWidgetItem(f"{timestamp}\n{text}")
        item.setData(0x0100, text)  # Qt.UserRole — the raw text to copy
        self._list.insertItem(0, item)
        while self._list.count() > self.MAX_TRANSCRIPTS:
            self._list.takeItem(self._list.count() - 1)

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        """Return a copy of cfg with this page's preferences applied."""
        cfg.auto_paste = self.auto_paste.isChecked()
        cfg.show_hud = self.show_hud.isChecked()
        cfg.language = self.language_combo.currentData() or "auto"
        return cfg

    # ------------------------------------------------------------------

    def _on_transcript_activated(self, item: QListWidgetItem) -> None:
        full_text = item.data(0x0100)
        if full_text:
            pyperclip.copy(full_text)

    def _refresh_summary(self) -> None:
        self._summary.setText(
            f"Hotkey {self._cfg.hotkey}  ·  Backend {self._cfg.backend}  "
            f"·  Model {self._cfg.local.model}"
        )


