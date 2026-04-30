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
    QComboBox,
    QHBoxLayout,
    QLabel,
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
    card_title,
)
from ..ui.widgets import preference_row


def _humanize_local_model(model_id: str) -> str:
    """Turn a faster-whisper model id into something readable.

    Examples:
        ``base`` → ``Base``
        ``tiny.en`` → ``Tiny (English)``
        ``distil-large-v3`` → ``Distil Large v3``
        ``large-v3`` → ``Large v3``
    """
    name = model_id
    suffix = ""
    if name.endswith(".en"):
        name = name[: -len(".en")]
        suffix = " (English)"
    parts = name.replace("_", "-").split("-")
    pretty = " ".join(p.title() if not p.startswith("v") else p for p in parts)
    return pretty + suffix


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

    # Emitted when the user toggles the Dark-mode switch. The bool is
    # the *requested* state (True → switch to dark). Lives on the home
    # page rather than the rail because the user feedback was that a
    # rail-level toggle felt strange — preferences belong with other
    # preferences. Persisted to Config via ``apply_to_config`` so the
    # choice survives a relaunch.
    theme_toggle_requested = Signal(bool)

    MAX_TRANSCRIPTS = 5

    def __init__(self, cfg: config_mod.Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        layout.addWidget(self._build_status_card())
        layout.addWidget(self._build_transcripts_card())
        layout.addWidget(self._build_preferences_card())
        layout.addStretch(1)

        self.set_state(State.IDLE)
        self._refresh_summary()

    # ------------------------------------------------------------------
    # Card builders
    # ------------------------------------------------------------------

    def _build_status_card(self) -> QWidget:
        """The marquee state of the app — a large status name + a dim
        summary line below. The previous treatment buried Idle/Recording
        in a 20-px row above a footnote; bumping it to 32 px makes the
        thing the user actually wants to see (am I recording?) the
        thing the eye lands on first."""
        status_card = card()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(22, 18, 22, 18)
        status_layout.setSpacing(8)

        self._state_dot = QLabel()
        self._state_dot.setFixedSize(18, 18)
        self._state_text = QLabel("Idle")
        self._state_text.setStyleSheet("font-size: 28px; font-weight: 700;")
        status_row = QHBoxLayout()
        status_row.setSpacing(14)
        status_row.addWidget(self._state_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self._state_text, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addStretch(1)
        status_layout.addLayout(status_row)

        self._summary = QLabel()
        self._summary.setProperty("dim", True)
        status_layout.addWidget(self._summary)
        return status_card

    def _build_transcripts_card(self) -> QWidget:
        """Recent transcripts as a card.

        We had a ``QStackedWidget`` here before to swap between an
        empty-state placeholder and a rows container. In the bundled
        .app the rows view never appeared — the rows container had
        nothing but a trailing stretch at first paint, so the stack's
        size hint collapsed when we flipped to it and the freshly
        added row was rendered into a zero-height region.

        Simpler shape: one container with the empty-state widget AND
        the rows. ``add_transcript`` hides the empty state on first
        arrival and inserts each new row above the previous newest.
        No stack, no size-hint games.
        """
        transcripts_card = card()
        layout = QVBoxLayout(transcripts_card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(card_title("Recent transcripts"))

        # Empty-state placeholder. Visible when ``_rows`` is empty;
        # hidden by ``add_transcript`` once a real row arrives.
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(0, 24, 0, 24)
        empty_layout.setSpacing(6)
        headline = QLabel("No recordings yet")
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        headline.setStyleSheet("font-size: 14px; font-weight: 600;")
        empty_layout.addWidget(headline)
        sub = QLabel(
            "Hold your hotkey and speak. Your last 5 transcripts will "
            "show up here for quick re-copying."
        )
        sub.setProperty("dim", True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        empty_layout.addWidget(sub)
        empty_layout.addStretch(1)
        self._empty_state = empty

        # Single container holds the empty-state and the row stack.
        # Rows are inserted above the empty-state; the stretch at the
        # bottom keeps everything top-aligned.
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addWidget(self._empty_state)
        self._rows_layout.addStretch(1)
        # Tracks the visible row widgets newest-first so trimming and
        # tests can introspect the order without walking the layout.
        self._rows: list[_TranscriptRow] = []
        layout.addLayout(self._rows_layout)
        return transcripts_card

    def _build_preferences_card(self) -> QWidget:
        """Preferences card: title + four toggle rows + language picker.

        Each toggle row is label-on-left, switch-on-right (per user
        feedback that the bare checkboxes felt like office software).
        Each switch keeps its previous attribute name (``auto_paste``,
        ``show_hud``, ``play_beeps``) so existing tests that drive
        them via ``setChecked()`` / ``isChecked()`` keep passing —
        ``ToggleSwitch`` is a drop-in for ``QCheckBox`` at the API
        level since both subclass ``QAbstractButton``.
        """
        prefs_card = card()
        layout = QVBoxLayout(prefs_card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(card_title("Preferences"))

        auto_paste_row, self.auto_paste = preference_row(
            "Auto-paste at cursor",
            caption="When off, transcribed text only lands on the clipboard.",
            initial=self._cfg.auto_paste,
            on_toggled=lambda _: self.preferences_changed.emit(),
        )
        layout.addWidget(auto_paste_row)

        hud_row, self.show_hud = preference_row(
            "Show recording HUD",
            caption="A small pill near the bottom of the screen while you talk.",
            initial=self._cfg.show_hud,
            on_toggled=lambda _: self.preferences_changed.emit(),
        )
        layout.addWidget(hud_row)

        beeps_row, self.play_beeps = preference_row(
            "Start / stop beeps",
            caption="Off = Silent mode (no audible cue when recording).",
            initial=self._cfg.play_beeps,
            on_toggled=lambda _: self.preferences_changed.emit(),
        )
        layout.addWidget(beeps_row)

        # Dark mode — initial state comes from the persisted Config so
        # the switch reflects whatever the user picked last session
        # (defaulting to off / light mode on a fresh install). Toggling
        # both requests an immediate theme swap *and* rides
        # preferences_changed so the new value lands on disk.
        def _on_dark_toggled(checked: bool) -> None:
            self.theme_toggle_requested.emit(checked)
            self.preferences_changed.emit()

        dark_row, self.dark_mode = preference_row(
            "Dark mode",
            caption="Use the dark palette across the app.",
            initial=self._cfg.dark_mode,
            on_toggled=_on_dark_toggled,
        )
        layout.addWidget(dark_row)

        # Language: dim caption above the dropdown rather than a
        # colon-style "Language:" label to the left. Reads more like
        # a modern preferences sheet, less like a 1995 form.
        lang_caption = QLabel("Language")
        lang_caption.setProperty("dim", True)
        layout.addSpacing(4)
        layout.addWidget(lang_caption)
        self.language_combo = QComboBox()
        for code, label in LANGUAGES:
            self.language_combo.addItem(f"{label} ({code})", userData=code)
        idx = next(
            (i for i, (code, _) in enumerate(LANGUAGES) if code == self._cfg.language),
            0,
        )
        self.language_combo.setCurrentIndex(idx)
        self.language_combo.currentIndexChanged.connect(
            lambda _: self.preferences_changed.emit(),
        )
        layout.addWidget(self.language_combo)
        return prefs_card

    # ------------------------------------------------------------------
    # Public hooks driven by the main window
    # ------------------------------------------------------------------

    def set_state(self, s: State) -> None:
        label, color = _STATE_LABELS.get(s, _STATE_LABELS[State.IDLE])
        self._state_text.setText(label)
        self._state_dot.setStyleSheet(
            f"background: {color}; border-radius: 9px;",
        )

    def set_config(self, cfg: config_mod.Config) -> None:
        """Sync the displayed preferences with a fresh Config."""
        self._cfg = cfg
        widgets = (
            self.auto_paste, self.show_hud, self.play_beeps,
            self.dark_mode, self.language_combo,
        )
        for w in widgets:
            w.blockSignals(True)
        self.auto_paste.setChecked(cfg.auto_paste)
        self.show_hud.setChecked(cfg.show_hud)
        self.play_beeps.setChecked(cfg.play_beeps)
        self.dark_mode.setChecked(cfg.dark_mode)
        idx = next(
            (i for i, (code, _) in enumerate(LANGUAGES) if code == cfg.language),
            0,
        )
        self.language_combo.setCurrentIndex(idx)
        for w in widgets:
            w.blockSignals(False)
        self._refresh_summary()

    def add_transcript(self, text: str, when: datetime | None = None) -> None:
        if not text:
            return
        timestamp = (when or datetime.now()).strftime("%H:%M")
        row = _TranscriptRow(text=text, timestamp=timestamp)
        row.clicked.connect(lambda t=text: pyperclip.copy(t))
        # Hide the empty state once a real transcript arrives. Cheaper
        # than reshuffling layouts and doesn't depend on the stack's
        # size hint changing.
        self._empty_state.hide()
        # Insert at index 0 so newest is on top; the empty-state widget
        # and trailing stretch shift down by one slot per prepended row.
        self._rows_layout.insertWidget(0, row)
        self._rows.insert(0, row)
        while len(self._rows) > self.MAX_TRANSCRIPTS:
            old = self._rows.pop()
            self._rows_layout.removeWidget(old)
            old.deleteLater()

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        """Return a copy of cfg with this page's preferences applied."""
        cfg.auto_paste = self.auto_paste.isChecked()
        cfg.show_hud = self.show_hud.isChecked()
        cfg.play_beeps = self.play_beeps.isChecked()
        cfg.dark_mode = self.dark_mode.isChecked()
        cfg.language = self.language_combo.currentData() or "auto"
        return cfg

    # ------------------------------------------------------------------

    def _refresh_summary(self) -> None:
        """Render the dim sub-line under the Status hero in plain English.

        The previous text was ``Hotkey <fn> · Backend local · Model
        tiny.en`` — angle-bracket spec syntax + raw provider IDs reads
        too technical for an end-user UI. This version uses
        :func:`hotkey_recorder.humanize` for the key spec and friendly
        labels for the backend / model.
        """
        from ..hotkey_recorder import humanize

        hotkey_pretty = humanize(self._cfg.hotkey)
        if self._cfg.backend == "local":
            backend_label = "On-device"
            model = (
                _humanize_local_model(self._cfg.local.model)
                if self._cfg.local.model
                else "(pick one in Models)"
            )
        else:
            from .. import providers as providers_mod

            provider = providers_mod.get_cloud(self._cfg.cloud_provider_id)
            backend_label = (
                provider.label if provider is not None
                else self._cfg.cloud_provider_id.title()
            )
            if self._cfg.cloud_provider_id == "openai":
                model = self._cfg.openai.model
            elif provider is not None:
                model = provider.default_model
            else:
                model = "(unknown)"
        self._summary.setText(
            f"{hotkey_pretty}  ·  {backend_label}  ·  {model}",
        )


class _TranscriptRow(QWidget):
    """Clickable row widget for a single transcript.

    Body text is the primary content and wraps freely; the timestamp
    sits on the right as a small dim caption. Clicking anywhere on
    the row emits :attr:`clicked` so the page can copy the text back
    to the clipboard.
    """

    clicked = Signal()

    def __init__(
        self,
        *,
        text: str,
        timestamp: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("transcriptRow")
        self.setProperty("clickable", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.text = text
        self.timestamp = timestamp

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        )
        # The label shouldn't intercept clicks — let them bubble to the
        # row's mousePressEvent so click-to-copy works anywhere on the
        # row, including over the text itself.
        body.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(body, 1)

        ts = QLabel(timestamp)
        ts.setProperty("dim", True)
        ts.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        ts.setMinimumWidth(40)
        ts.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(ts, 0)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
