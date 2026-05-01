"""First-run onboarding wizard (4 steps).

Issue: #20.

Walks a fresh-install user through the four things Murmuro needs to be
useful:

  1. Permissions  — Microphone + Input Monitoring + Accessibility.
  2. A model      — pick one from the curated faster-whisper list.
  3. A hotkey     — bind push-to-talk to a key they like.
  4. Try it now   — verify end-to-end transcription works.

Every step has a **Skip — I'll do this later** link. Skipping at any
point flips ``Config.onboarded = True`` so we don't re-prompt next
launch; the Home page surfaces a resume banner so the user can come
back when ready.

Existing users (config.toml that pre-dates this flag, or who already
picked a local model) skip the wizard entirely — see
``config.load`` for the migration heuristic.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import config as config_mod
from . import providers as providers_mod
from ._logging import get_logger
from .hotkey_recorder import HotkeyRecorder, humanize
from .permissions import (
    AccessibilityStatus,
    InputMonitoringStatus,
    accessibility_status,
    input_monitoring_status,
    open_accessibility_settings,
    open_input_monitoring_settings,
    request_input_monitoring,
)
from .ui.theme import card, card_title, hint_label, primary_button

_log = get_logger("onboarding")


# ---------------------------------------------------------------------------


@dataclass
class OnboardingResult:
    """What the wizard returns to its caller.

    ``completed`` means the user reached step 4. ``skipped`` means they
    bailed out at any earlier step. Either way we set
    ``cfg.onboarded = True`` on disk so the wizard doesn't re-fire.
    Apply ``cfg`` to keep model/hotkey/etc. picks the user made along
    the way.
    """

    completed: bool
    skipped: bool
    cfg: config_mod.Config


class OnboardingWizard(QDialog):
    """4-step modal wizard. See module docstring for the flow."""

    STEPS = ("Welcome", "Model", "Hotkey", "Try it")

    def __init__(
        self,
        cfg: config_mod.Config,
        *,
        save_config: Callable[[config_mod.Config], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._save_config = save_config or config_mod.save
        self._skipped = False

        self.setWindowTitle("Welcome to Murmuro")
        self.setModal(True)
        self.setMinimumSize(640, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        # Header — current step name + 1-of-N indicator. Updated when
        # the stack page changes via ``_set_step``.
        self._header = QLabel()
        self._header.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(self._header)
        self._sub_header = QLabel()
        self._sub_header.setProperty("dim", True)
        layout.addWidget(self._sub_header)

        self._stack = QStackedWidget()
        self._welcome = _WelcomeStep()
        self._model = _ModelStep(cfg)
        self._hotkey = _HotkeyStep(cfg)
        self._try_it = _TryItStep()
        for step in (self._welcome, self._model, self._hotkey, self._try_it):
            self._stack.addWidget(step)
        layout.addWidget(self._stack, 1)

        # Footer — Back on the left, Skip + Next on the right. Mac-style.
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self._back_btn = QPushButton("Back")
        self._back_btn.clicked.connect(self._on_back)
        self._skip_btn = QPushButton("Skip — I'll do this later")
        self._skip_btn.setProperty("link", True)
        self._skip_btn.clicked.connect(self._on_skip)
        self._next_btn = primary_button("Next")
        self._next_btn.clicked.connect(self._on_next)
        footer.addWidget(self._back_btn)
        footer.addStretch(1)
        footer.addWidget(self._skip_btn)
        footer.addWidget(self._next_btn)
        layout.addLayout(footer)

        self._set_step(0)

    # ----- Public API ---------------------------------------------------

    def result(self) -> OnboardingResult:
        """Snapshot of where the wizard ended up.

        Persisted ``cfg.onboarded`` should already be ``True`` when this
        is called (set by ``_finish`` / ``_on_skip``); we re-stamp here
        too so the caller can rely on the flag without thinking about
        the order of operations.
        """
        cfg = self._collect_config()
        cfg.onboarded = True
        return OnboardingResult(
            completed=(not self._skipped),
            skipped=self._skipped,
            cfg=cfg,
        )

    # ----- Step transitions ---------------------------------------------

    def _set_step(self, idx: int) -> None:
        if not 0 <= idx < self._stack.count():
            return
        self._stack.setCurrentIndex(idx)
        self._header.setText(f"Step {idx + 1} of {len(self.STEPS)} — {self.STEPS[idx]}")
        self._sub_header.setText(self._stack.currentWidget().sub_header())
        self._back_btn.setVisible(idx > 0)
        self._next_btn.setText("Finish" if idx == len(self.STEPS) - 1 else "Next")

    def _on_back(self) -> None:
        self._set_step(self._stack.currentIndex() - 1)

    def _on_next(self) -> None:
        idx = self._stack.currentIndex()
        if idx >= len(self.STEPS) - 1:
            self._finish()
            return
        self._set_step(idx + 1)

    def _on_skip(self) -> None:
        self._skipped = True
        self._persist_partial()
        self.accept()

    def _finish(self) -> None:
        self._skipped = False
        self._persist_partial()
        self.accept()

    def _collect_config(self) -> config_mod.Config:
        """Apply each step's user input back onto the cfg draft.

        Each step has an ``apply_to_config`` so the wizard doesn't
        need to know the schema details — same pattern as the main
        window pages.
        """
        cfg = self._cfg
        cfg = self._welcome.apply_to_config(cfg)
        cfg = self._model.apply_to_config(cfg)
        cfg = self._hotkey.apply_to_config(cfg)
        return cfg

    def _persist_partial(self) -> None:
        """Save whatever the user picked, plus the onboarded flag.

        Called by both Skip and Finish so a partial walkthrough still
        captures (e.g.) the hotkey if they bailed at step 4.
        """
        cfg = self._collect_config()
        cfg.onboarded = True
        try:
            self._save_config(cfg)
            self._cfg = cfg
        except Exception:  # noqa: BLE001
            _log.exception("failed to persist onboarding config")


# ---- Step widgets ----------------------------------------------------------


class _Step(QWidget):
    """Base type for wizard steps. Subclasses provide a sub-header
    line and an optional ``apply_to_config`` hook."""

    def sub_header(self) -> str:
        return ""

    def apply_to_config(
        self, cfg: config_mod.Config,
    ) -> config_mod.Config:
        return cfg


class _WelcomeStep(_Step):
    """Step 1 — Welcome + permission triggers."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(14)

        intro = QLabel(
            "Murmuro turns your voice into text at the cursor — hold a "
            "hotkey, speak, release. Before we get going, macOS needs "
            "two permissions to make this work."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        c = card()
        col = QVBoxLayout(c)
        col.setContentsMargins(20, 16, 20, 16)
        col.setSpacing(12)
        col.addWidget(card_title("Permissions"))

        self._input_row, self._input_status = _permission_row(
            label="Input Monitoring",
            description="Lets Murmuro see your global hotkey from any app.",
            on_grant=self._grant_input_monitoring,
        )
        col.addWidget(self._input_row)

        self._access_row, self._access_status = _permission_row(
            label="Accessibility",
            description="Lets Murmuro paste transcribed text at the cursor "
                        "(without it, transcripts still land on the clipboard).",
            on_grant=self._grant_accessibility,
        )
        col.addWidget(self._access_row)

        layout.addWidget(c)
        layout.addWidget(hint_label(
            "Microphone access is requested by macOS the first time you "
            "press your hotkey in step 4 — no extra click here."
        ))
        layout.addStretch(1)
        self._refresh_status()

        # Permissions can land asynchronously (the user toggles them
        # in System Settings between window paints). A 1-second poll
        # keeps the labels fresh so the user doesn't stare at a
        # "Denied" line they just fixed. Stops automatically when
        # the widget is deleted.
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._refresh_status)
        self._poll.start()

    def sub_header(self) -> str:
        return "Grant permissions so Murmuro can hear your hotkey and paste at the cursor."

    def _refresh_status(self) -> None:
        im = input_monitoring_status()
        self._input_status.setText(_im_label(im))
        ax = accessibility_status()
        self._access_status.setText(_ax_label(ax))

    def _grant_input_monitoring(self) -> None:
        # First-time call triggers the system prompt; subsequent calls
        # open Settings since macOS won't re-prompt.
        if input_monitoring_status() == InputMonitoringStatus.UNKNOWN:
            request_input_monitoring()
        else:
            open_input_monitoring_settings()
        self._refresh_status()

    def _grant_accessibility(self) -> None:
        # macOS won't prompt for accessibility — only Settings shows it.
        open_accessibility_settings()
        self._refresh_status()


def _im_label(status: InputMonitoringStatus) -> str:
    return {
        InputMonitoringStatus.GRANTED: "✓ Granted",
        InputMonitoringStatus.DENIED: "⚠ Denied",
        InputMonitoringStatus.UNKNOWN: "Not yet asked",
        InputMonitoringStatus.UNAVAILABLE: "Not applicable",
    }.get(status, str(status))


def _ax_label(status: AccessibilityStatus) -> str:
    return {
        AccessibilityStatus.GRANTED: "✓ Granted",
        AccessibilityStatus.DENIED: "⚠ Not granted",
        AccessibilityStatus.UNAVAILABLE: "Not applicable",
    }.get(status, str(status))


def _permission_row(
    *, label: str, description: str, on_grant: Callable[[], None],
) -> tuple[QWidget, QLabel]:
    """Build a row with: label + description on left, status + grant button
    on right. The status label is returned so the caller can refresh it
    when the user comes back from System Settings."""
    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(12)

    text_col = QVBoxLayout()
    text_col.setSpacing(2)
    name = QLabel(label)
    name.setStyleSheet("font-weight: 600;")
    text_col.addWidget(name)
    desc = QLabel(description)
    desc.setProperty("dim", True)
    desc.setWordWrap(True)
    text_col.addWidget(desc)
    row_layout.addLayout(text_col, 1)

    status = QLabel()
    status.setProperty("dim", True)
    row_layout.addWidget(status)

    btn = QPushButton("Grant…")
    btn.clicked.connect(on_grant)
    row_layout.addWidget(btn)
    return row, status


# ---- Step 2: Model --------------------------------------------------------


class _ModelStep(_Step):
    """Step 2 — pick a curated local model."""

    # Surface only the smaller curated entries here so the wizard
    # doesn't suggest a 1.5GB+ download on first run. Power users can
    # pick larger models on the Models page later.
    _RECOMMENDED_MODEL_IDS = ("base", "tiny.en", "base.en", "small")

    def __init__(self, cfg: config_mod.Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(14)

        intro = QLabel(
            "Murmuro runs a small Whisper model on your machine. The "
            "default — Base — is a good balance: ~145 MB to download, "
            "fast on any modern Mac, accurate enough for dictation."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        c = card()
        col = QVBoxLayout(c)
        col.setContentsMargins(20, 16, 20, 16)
        col.setSpacing(10)
        col.addWidget(card_title("Choose a model"))

        self._combo = QComboBox()
        for model_id in self._RECOMMENDED_MODEL_IDS:
            model = providers_mod.find_local_model(model_id)
            if model is None:
                continue
            label = f"{model.label} — {model.size_mb} MB"
            if model_id == "base":
                label += "  (recommended)"
            self._combo.addItem(label, userData=model_id)
        # Default to whatever cfg already has, falling back to base.
        target = cfg.local.model or "base"
        idx = max(0, self._combo.findData(target))
        self._combo.setCurrentIndex(idx)
        col.addWidget(self._combo)

        # Progress placeholder. Real download wiring is the responsibility
        # of the caller (we just record the user's pick); this bar is
        # a light affordance reminding the user that we'll start the
        # download when they finish onboarding.
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        col.addWidget(self._progress)

        layout.addWidget(c)
        layout.addWidget(hint_label(
            "Download starts in the background after you finish the wizard. "
            "You can switch models any time on the Models page."
        ))
        layout.addStretch(1)

    def sub_header(self) -> str:
        return "Pick which Whisper model Murmuro should use."

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        choice = self._combo.currentData()
        if choice:
            cfg.local.model = choice
        return cfg


# ---- Step 3: Hotkey -------------------------------------------------------


class _HotkeyStep(_Step):
    """Step 3 — pick a push-to-talk hotkey."""

    def __init__(self, cfg: config_mod.Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(14)

        intro = QLabel(
            "Pick a key you don't use for anything else. The default — "
            f"{humanize(cfg.hotkey)} — is a good choice on most "
            "keyboards. To change, click Record and press the key you "
            "want."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        c = card()
        col = QVBoxLayout(c)
        col.setContentsMargins(20, 16, 20, 16)
        col.setSpacing(10)
        col.addWidget(card_title("Push-to-talk hotkey"))

        # Reuse the same recorder widget the Shortcuts page uses so
        # the visual + keyboard handling stays consistent.
        self._recorder = HotkeyRecorder(cfg.hotkey)
        col.addWidget(self._recorder)

        layout.addWidget(c)
        layout.addStretch(1)

    def sub_header(self) -> str:
        return "Bind the push-to-talk key. You can change this later in Shortcuts."

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        cfg.hotkey = self._recorder.value() or cfg.hotkey
        return cfg


# ---- Step 4: Try it -------------------------------------------------------


class _TryItStep(_Step):
    """Step 4 — show the bound hotkey and tell the user to try it.

    Live-test wiring (actually capturing audio inside the wizard) is
    deferred — the wizard closes on Finish, the main window opens, and
    the user can immediately push-to-talk. This step is informational
    so we don't double-build the recording pipeline inside a modal.
    """

    triggered = Signal()  # reserved for future "live" preview

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(14)

        c = card()
        col = QVBoxLayout(c)
        col.setContentsMargins(24, 22, 24, 22)
        col.setSpacing(10)
        title = QLabel("You're set.")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        col.addWidget(title)
        col.addWidget(QLabel(
            "Click Finish to close this wizard. Murmuro will sit in the "
            "menu bar — hold your hotkey from any app, speak, and your "
            "words will appear at the cursor.\n\n"
            "If something doesn't work, the Home page will tell you "
            "what's missing."
        ))
        layout.addWidget(c)
        layout.addStretch(1)

    def sub_header(self) -> str:
        return "Hold your hotkey from any app to dictate."


__all__ = ["OnboardingWizard", "OnboardingResult"]
