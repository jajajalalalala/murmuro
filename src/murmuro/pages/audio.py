"""Audio page: pick which microphone Murmuro records from.

Pulls the current device list from ``audio.list_input_devices`` and
exposes a dropdown that writes back to ``Config.input_device`` (a
human-readable device name; empty string = system default).

Deliberately small for now — sample-rate / gain / monitoring would
slot in here if they ever earn their way in. The page is its own
nav destination so the tray menu's "Microphone input…" jump lands
the user directly on the dropdown.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config as config_mod
from ..audio import list_input_devices
from ..ui.theme import card, card_title, hint_label


class AudioPage(QWidget):
    """Single-card page with the input-device picker."""

    preferences_changed = Signal()

    def __init__(self, cfg: config_mod.Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)
        layout.addWidget(self._build_input_card())
        layout.addWidget(hint_label(
            "Murmuro records at 16 kHz mono — most modern mics, including "
            "AirPods and the built-in MacBook mic, work without any tuning."
        ))
        layout.addStretch(1)

    # ------------------------------------------------------------------

    def _build_input_card(self) -> QWidget:
        c = card()
        col = QVBoxLayout(c)
        col.setContentsMargins(20, 16, 20, 16)
        col.setSpacing(10)
        col.addWidget(card_title("Microphone input"))

        caption = QLabel("Choose which input Murmuro should listen to.")
        caption.setProperty("dim", True)
        col.addWidget(caption)

        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(
            lambda _: self.preferences_changed.emit(),
        )
        col.addWidget(self.device_combo)

        # Refresh button so the user can re-enumerate after plugging /
        # unplugging a USB device without quitting Murmuro.
        refresh = QPushButton("Refresh device list")
        refresh.clicked.connect(self.refresh_devices)
        col.addWidget(refresh)

        # Populate on first paint with the saved selection pre-picked.
        self.refresh_devices()
        return c

    # ------------------------------------------------------------------

    def refresh_devices(self) -> None:
        """Re-enumerate input devices and refresh the dropdown.

        Called on construction and when the user clicks Refresh. Picks
        up newly plugged mics and drops disappeared ones. Preserves
        the saved selection if it's still present.
        """
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        # First entry is always "system default" with a None userData so
        # the page can offer a graceful fallback for users who don't
        # want to pin a specific device.
        self.device_combo.addItem("System default", userData="")
        devices = list_input_devices()
        target = self._cfg.input_device
        target_idx = 0
        for dev in devices:
            label = dev.name + (" (system default)" if dev.is_default else "")
            self.device_combo.addItem(label, userData=dev.name)
            if dev.name == target:
                target_idx = self.device_combo.count() - 1
        self.device_combo.setCurrentIndex(target_idx)
        self.device_combo.blockSignals(False)

    def set_config(self, cfg: config_mod.Config) -> None:
        self._cfg = cfg
        self.refresh_devices()

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        cfg.input_device = self.device_combo.currentData() or ""
        return cfg


__all__ = ["AudioPage"]
