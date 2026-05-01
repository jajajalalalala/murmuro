"""About page: version, credits, and pointers to logs/config.

Read-only. Useful when something looks wrong and the user (or whoever
they're asking for help) needs to find the log file or see what
version is running. The "Open in Finder" / "Reveal" buttons let users
get there without remembering ``~/Library/Logs/Murmuro``.
"""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .. import config as config_mod
from .._logging import log_path
from ..ui.theme import (
    card,
    card_title,
    hint_label,
    mono_label,
    primary_button,
)

GITHUB_URL = "https://github.com/jajajalalalala/murmuro"


class AboutPage(QWidget):
    """Static info panel — never emits preferences_changed."""

    preferences_changed = Signal()  # never emitted; here so MainWindow's
    # change-bus stays uniform across pages.

    def __init__(self, cfg: config_mod.Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        # --- Identity card -------------------------------------------------
        identity = card()
        identity_layout = QVBoxLayout(identity)
        identity_layout.setContentsMargins(20, 18, 20, 18)
        identity_layout.setSpacing(6)
        title = QLabel("Murmuro")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        identity_layout.addWidget(title)
        version = QLabel(f"Version {__version__}")
        version.setProperty("dim", True)
        identity_layout.addWidget(version)
        blurb = QLabel(
            "Push-to-talk dictation for macOS. Hold your hotkey, speak, "
            "release — Murmuro transcribes locally with faster-whisper or "
            "via your chosen cloud provider, then drops the text at your "
            "cursor."
        )
        blurb.setWordWrap(True)
        identity_layout.addWidget(blurb)
        layout.addWidget(identity)

        # --- Quick info ----------------------------------------------------
        # Sentence-case captions stacked above the values, no colons —
        # the previous "Hotkey:" / "Backend:" form layout looked like a
        # 1995 preferences dialog.
        info_card = card()
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(20, 16, 20, 16)
        info_layout.setSpacing(10)
        info_layout.addWidget(card_title("Current setup"))

        info_grid = QFormLayout()
        info_grid.setContentsMargins(0, 4, 0, 0)
        info_grid.setHorizontalSpacing(20)
        info_grid.setVerticalSpacing(6)
        info_grid.setLabelAlignment(_qt().AlignmentFlag.AlignLeft)

        def _caption(text: str) -> QLabel:
            cap = QLabel(text)
            cap.setProperty("dim", True)
            return cap

        self._hotkey_value = QLabel(_humanize_hotkey(self._cfg.hotkey))
        self._backend_value = QLabel(_humanize_backend(self._cfg))
        self._model_value = QLabel(self._describe_model(cfg))
        info_grid.addRow(_caption("Hotkey"), self._hotkey_value)
        info_grid.addRow(_caption("Backend"), self._backend_value)
        info_grid.addRow(_caption("Model"), self._model_value)
        info_grid.addRow(_caption("Python"), QLabel(sys.version.split()[0]))
        info_grid.addRow(_caption("Platform"), QLabel(_platform_label()))
        info_layout.addLayout(info_grid)
        layout.addWidget(info_card)

        # --- Files ---------------------------------------------------------
        # Each file is a stack: dim caption above the monospace path, with
        # the Reveal button right-aligned. Cleaner than the original
        # cramped one-line layout the user flagged as "weird display".
        files_card = card()
        files_layout = QVBoxLayout(files_card)
        files_layout.setContentsMargins(20, 16, 20, 16)
        files_layout.setSpacing(12)
        files_layout.addWidget(card_title("Files"))
        files_layout.addWidget(
            _file_row("Config", config_mod.config_path())
        )
        files_layout.addWidget(_file_row("Log", log_path()))
        layout.addWidget(files_card)

        # --- Links ---------------------------------------------------------
        links_row = QHBoxLayout()
        links_row.setSpacing(10)
        github_btn = primary_button("View on GitHub")
        github_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL))
        )
        links_row.addWidget(github_btn)
        links_row.addStretch(1)
        layout.addLayout(links_row)

        layout.addWidget(hint_label(
            "Murmuro runs entirely on your machine when you pick the local "
            "backend — audio never leaves the device unless you choose a "
            "cloud provider."
        ))

        layout.addStretch(1)

    # ------------------------------------------------------------------

    def set_config(self, cfg: config_mod.Config) -> None:
        self._cfg = cfg
        self._hotkey_value.setText(_humanize_hotkey(cfg.hotkey))
        self._backend_value.setText(_humanize_backend(cfg))
        self._model_value.setText(self._describe_model(cfg))

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        # About is read-only; nothing to write back.
        return cfg

    @staticmethod
    def _describe_model(cfg: config_mod.Config) -> str:
        """Friendly model description: ``Base — 145 MB · Multilingual``.

        Looks up the model in the curated registry to surface its
        size and English/multilingual flavor; unknown ids (e.g.
        hand-edited TOML) fall through to the raw id so we never
        hide the truth from the user.
        """
        if cfg.backend == "local":
            mid = cfg.local.model
            if not mid:
                return "(none selected)"
            from .. import providers as providers_mod
            entry = providers_mod.find_local_model(mid)
            if entry is None:
                return mid
            size = (
                f"{entry.size_mb / 1024:.1f} GB" if entry.size_mb >= 1024
                else f"{entry.size_mb} MB"
            )
            flavor = "Multilingual" if entry.multilingual else "English-only"
            return f"{entry.label} — {size} · {flavor}"
        if cfg.cloud_provider_id == "openai":
            return cfg.openai.model
        from .. import providers as providers_mod

        provider = providers_mod.get_cloud(cfg.cloud_provider_id)
        return provider.default_model if provider else "(unknown)"


def _platform_label() -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def _humanize_hotkey(spec: str) -> str:
    """Render a hotkey spec like ``<left_ctrl>`` as ``Left Control``.

    Reuses the recorder's pretty-printer so the About page agrees with
    the Shortcuts page and the Home status line.
    """
    from ..hotkey_recorder import humanize
    return humanize(spec)


def _humanize_backend(cfg: config_mod.Config) -> str:
    """Render the backend axis as something a non-engineer can read.

    ``local`` becomes ``On-device``; ``cloud`` shows the provider's
    display name (e.g. ``OpenAI Whisper``) instead of a bare id.
    """
    if cfg.backend == "local":
        return "On-device"
    from .. import providers as providers_mod
    provider = providers_mod.get_cloud(cfg.cloud_provider_id)
    if provider is not None:
        return provider.label
    return cfg.cloud_provider_id.title()


def _qt():
    """Lazy import of Qt so the module imports cleanly even if QtCore
    isn't pre-loaded yet (which can happen under strict offscreen test
    setups). Returning the module is enough — callers reach the enum
    through it."""
    from PySide6.QtCore import Qt
    return Qt


def _file_row(label: str, path: Path) -> QWidget:
    """A two-line row: dim caption + monospace path, with a right-
    aligned Reveal button vertically centered."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    text_col = QVBoxLayout()
    text_col.setContentsMargins(0, 0, 0, 0)
    text_col.setSpacing(2)
    caption = QLabel(label)
    caption.setProperty("dim", True)
    text_col.addWidget(caption)
    path_label = mono_label(str(path))
    path_label.setWordWrap(False)
    text_col.addWidget(path_label)
    layout.addLayout(text_col, 1)

    open_btn = QPushButton("Reveal")
    open_btn.clicked.connect(lambda: _reveal_in_finder(path))
    layout.addWidget(open_btn, 0, _qt().AlignmentFlag.AlignVCenter)
    return row


def _selectable_flag():
    return _qt().TextInteractionFlag.TextSelectableByMouse


def _reveal_in_finder(path: Path) -> None:
    """Open the parent folder, highlighting the file when possible.

    macOS: ``open -R`` reveals in Finder. Linux/Windows: fall back to the
    parent directory via ``QDesktopServices``.
    """
    target = Path(path)
    if not target.exists():
        target = target.parent
    if sys.platform == "darwin":
        try:
            subprocess.run(["open", "-R", str(target)], check=False)
            return
        except Exception:  # noqa: BLE001
            pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent if target.is_file() else target)))
