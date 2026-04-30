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
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
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

    # Emitted when the user toggles the Dark-mode checkbox. The bool is
    # the *requested* state (True → switch to dark). Lives on the home
    # page rather than the rail because the user feedback was that a
    # rail-level toggle felt strange — preferences belong with other
    # preferences. Session-scoped (not persisted to Config yet).
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
        """Recent transcripts as a card. When empty, a friendly
        placeholder replaces the bare-rectangle empty state. Each
        transcript renders as a custom row widget (text + timestamp
        caption) so the page no longer reads like a terminal log."""
        transcripts_card = card()
        layout = QVBoxLayout(transcripts_card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(card_title("Recent transcripts"))

        self._list = QListWidget()
        self._list.setObjectName("transcripts")
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.setVerticalScrollMode(
            QListWidget.ScrollMode.ScrollPerPixel,
        )
        self._list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection,
        )
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self._list.setMinimumHeight(160)
        self._list.setMaximumHeight(280)
        self._list.itemActivated.connect(self._on_transcript_activated)

        # Empty-state placeholder. Swapped in via a QStackedWidget when
        # the list has zero rows; pages flip back to the list as soon
        # as the first transcript arrives.
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

        self._transcripts_stack = QStackedWidget()
        self._transcripts_stack.addWidget(self._empty_state)
        self._transcripts_stack.addWidget(self._list)
        self._transcripts_stack.setCurrentWidget(self._empty_state)
        layout.addWidget(self._transcripts_stack)
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

        # Dark mode — session-scoped so it doesn't ride preferences_changed
        # (no Config field for theme yet). Initial state mirrors the
        # currently-active palette so the switch reflects reality on
        # first paint.
        dark_row, self.dark_mode = preference_row(
            "Dark mode",
            caption="Use the dark palette across the app.",
            initial=self._is_palette_dark(),
            on_toggled=lambda checked: self.theme_toggle_requested.emit(checked),
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

    @staticmethod
    def _is_palette_dark() -> bool:
        """Inspect the active QApplication palette to decide whether the
        Dark-mode switch should start in the on position. Dark surfaces
        have a window-color lightness below ~128 (out of 255)."""
        app = QApplication.instance()
        if app is None:
            return False
        color = app.palette().color(QPalette.ColorRole.Window)
        return color.lightness() < 128

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
        widgets = (self.auto_paste, self.show_hud, self.play_beeps, self.language_combo)
        for w in widgets:
            w.blockSignals(True)
        self.auto_paste.setChecked(cfg.auto_paste)
        self.show_hud.setChecked(cfg.show_hud)
        self.play_beeps.setChecked(cfg.play_beeps)
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
        item = QListWidgetItem()
        # No item text — the custom row widget below is what the user
        # sees, and Qt would otherwise double-paint the item's default
        # text behind the widget. We stash the timestamp + raw text in
        # item-data roles so tests / future delegates can introspect.
        item.setData(Qt.ItemDataRole.UserRole, text)
        item.setData(Qt.ItemDataRole.UserRole + 1, timestamp)
        item.setSizeHint(_TranscriptRow.sizeHintFor(text))
        self._list.insertItem(0, item)
        self._list.setItemWidget(
            self._list.item(0),
            _TranscriptRow(text=text, timestamp=timestamp),
        )
        while self._list.count() > self.MAX_TRANSCRIPTS:
            self._list.takeItem(self._list.count() - 1)

        # First transcript switches the stack to the list view.
        if self._transcripts_stack.currentWidget() is self._empty_state:
            self._transcripts_stack.setCurrentWidget(self._list)

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        """Return a copy of cfg with this page's preferences applied."""
        cfg.auto_paste = self.auto_paste.isChecked()
        cfg.show_hud = self.show_hud.isChecked()
        cfg.play_beeps = self.play_beeps.isChecked()
        cfg.language = self.language_combo.currentData() or "auto"
        return cfg

    # ------------------------------------------------------------------

    def _on_transcript_activated(self, item: QListWidgetItem) -> None:
        full_text = item.data(Qt.ItemDataRole.UserRole)
        if full_text:
            pyperclip.copy(full_text)

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
    """Custom row widget for a single transcript.

    Body text is the primary content and wraps freely; the timestamp
    sits on the right as a small dim caption. Replaces the previous
    ``"14:32\\ntext"`` two-line list-item rendering that the user
    flagged as looking like terminal output.
    """

    _PADDING = (8, 6, 8, 6)

    def __init__(
        self,
        *,
        text: str,
        timestamp: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(*self._PADDING)
        layout.setSpacing(12)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        )
        layout.addWidget(body, 1)

        ts = QLabel(timestamp)
        ts.setProperty("dim", True)
        ts.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        ts.setMinimumWidth(40)
        layout.addWidget(ts, 0)

    @classmethod
    def sizeHintFor(cls, text: str) -> _QSize:  # noqa: N802 — Qt camelCase
        """Heuristic height so the parent QListWidget allocates enough
        room without needing a delegate. Long transcripts wrap and we
        bump the row height accordingly."""
        from PySide6.QtCore import QSize
        # ~50 chars per line at our default body font size; hand-tuned.
        chars_per_line = 56
        lines = max(1, (len(text) + chars_per_line - 1) // chars_per_line)
        line_h = 20
        pad_v = cls._PADDING[1] + cls._PADDING[3]
        return QSize(0, lines * line_h + pad_v)


# Forward reference for the type annotation above so the module imports
# cleanly when Qt isn't installed (e.g. lint passes).
_QSize = "QSize"
