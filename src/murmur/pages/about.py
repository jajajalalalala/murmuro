"""About page: version, credits, and pointers to logs/config.

Read-only. Useful when something looks wrong and the user (or whoever
they're asking for help) needs to find the log file or see what
version is running. The "Open in Finder" / "Reveal" buttons let users
get there without remembering ``~/Library/Logs/Murmur``.
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
from ..ui.theme import card, hint_label, primary_button, section_label

GITHUB_URL = "https://github.com/jajajalalalala/murmur"


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
        layout.addWidget(section_label("Murmur"))
        identity = card()
        identity_layout = QVBoxLayout(identity)
        identity_layout.setContentsMargins(20, 16, 20, 16)
        identity_layout.setSpacing(6)
        title = QLabel("Murmur")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        identity_layout.addWidget(title)
        version = QLabel(f"Version {__version__}")
        version.setProperty("dim", True)
        identity_layout.addWidget(version)
        blurb = QLabel(
            "Push-to-talk dictation for macOS. Hold your hotkey, speak, "
            "release — Murmur transcribes locally with faster-whisper or "
            "via your chosen cloud provider, then drops the text at your "
            "cursor."
        )
        blurb.setWordWrap(True)
        identity_layout.addWidget(blurb)
        layout.addWidget(identity)

        # --- Quick info ----------------------------------------------------
        layout.addWidget(section_label("Current setup"))
        info_card = card()
        info_form = QFormLayout(info_card)
        info_form.setContentsMargins(20, 16, 20, 16)
        info_form.setHorizontalSpacing(16)
        info_form.setVerticalSpacing(8)
        self._hotkey_value = QLabel(self._cfg.hotkey)
        self._backend_value = QLabel(self._cfg.backend)
        self._model_value = QLabel(self._describe_model(cfg))
        info_form.addRow(QLabel("Hotkey:"), self._hotkey_value)
        info_form.addRow(QLabel("Backend:"), self._backend_value)
        info_form.addRow(QLabel("Model:"), self._model_value)
        info_form.addRow(QLabel("Python:"), QLabel(sys.version.split()[0]))
        info_form.addRow(QLabel("Platform:"), QLabel(_platform_label()))
        layout.addWidget(info_card)

        # --- Files ---------------------------------------------------------
        layout.addWidget(section_label("Files"))
        files_card = card()
        files_layout = QVBoxLayout(files_card)
        files_layout.setContentsMargins(20, 16, 20, 16)
        files_layout.setSpacing(8)
        files_layout.addWidget(_file_row("Config", config_mod.config_path()))
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
            "Murmur runs entirely on your machine when you pick the local "
            "backend — audio never leaves the device unless you choose a "
            "cloud provider."
        ))

        layout.addStretch(1)

    # ------------------------------------------------------------------

    def set_config(self, cfg: config_mod.Config) -> None:
        self._cfg = cfg
        self._hotkey_value.setText(cfg.hotkey)
        self._backend_value.setText(cfg.backend)
        self._model_value.setText(self._describe_model(cfg))

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        # About is read-only; nothing to write back.
        return cfg

    @staticmethod
    def _describe_model(cfg: config_mod.Config) -> str:
        if cfg.backend == "local":
            return cfg.local.model
        return getattr(cfg, cfg.backend, cfg.openai).model


def _platform_label() -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def _file_row(label: str, path: Path) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    name = QLabel(label)
    name.setMinimumWidth(60)
    value = QLabel(str(path))
    value.setProperty("dim", True)
    value.setTextInteractionFlags(value.textInteractionFlags()
                                  | _selectable_flag())
    open_btn = QPushButton("Reveal")
    open_btn.clicked.connect(lambda: _reveal_in_finder(path))
    layout.addWidget(name)
    layout.addWidget(value, 1)
    layout.addWidget(open_btn)
    return row


def _selectable_flag():
    from PySide6.QtCore import Qt
    return Qt.TextInteractionFlag.TextSelectableByMouse


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
