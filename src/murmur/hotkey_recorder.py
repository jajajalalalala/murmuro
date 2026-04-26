"""Click-to-record widget for capturing a hotkey by pressing it.

The user clicks "Record", presses the desired key (or combo) once, and the
widget commits the result in pynput-compatible spec form
(e.g. "<right_alt>", "<ctrl>+<shift>+<space>", "<f9>", "a"). The committed
spec is what `PushToTalkHotkey._parse_keys` already understands.

Single-modifier hotkeys (Right Option alone) are detected on key release
once the user lets go of the last modifier; combos with a non-modifier
key (Ctrl+Shift+Space) commit on the non-modifier press.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

# macOS virtual keycode → friendly name (matches pynput's KEY_ALIASES side).
# We only enumerate the keys most reach for as push-to-talk hotkeys.
_MAC_VK_NAMES: dict[int, str] = {
    # Modifiers (left/right distinction matters)
    0x37: "left_cmd",
    0x36: "right_cmd",
    0x38: "left_shift",
    0x3C: "right_shift",
    0x3A: "left_alt",
    0x3D: "right_alt",
    0x3B: "left_ctrl",
    0x3E: "right_ctrl",
    # Function keys
    0x7A: "f1", 0x78: "f2", 0x63: "f3", 0x76: "f4",
    0x60: "f5", 0x61: "f6", 0x62: "f7", 0x64: "f8",
    0x65: "f9", 0x6D: "f10", 0x67: "f11", 0x6F: "f12",
    # Whitespace / control
    0x31: "space", 0x30: "tab", 0x35: "esc", 0x24: "enter",
}

_MAC_MODIFIER_VKS: frozenset[int] = frozenset({
    0x37, 0x36, 0x38, 0x3C, 0x3A, 0x3D, 0x3B, 0x3E,
})


def humanize(spec: str) -> str:
    """Turn a pynput spec into something readable in the dialog."""
    if not spec:
        return "(none)"
    parts = spec.split("+")
    pretty = []
    for raw in parts:
        token = raw.strip()
        if token.startswith("<") and token.endswith(">"):
            name = token[1:-1]
            pretty.append({
                "right_alt": "Right Option",
                "left_alt": "Left Option",
                "right_cmd": "Right Command",
                "left_cmd": "Left Command",
                "right_shift": "Right Shift",
                "left_shift": "Left Shift",
                "right_ctrl": "Right Control",
                "left_ctrl": "Left Control",
                "space": "Space",
                "tab": "Tab",
                "esc": "Esc",
                "enter": "Return",
            }.get(name, name.upper() if name.startswith("f") else name.title()))
        else:
            pretty.append(token.upper())
    return " + ".join(pretty)


class HotkeyRecorder(QWidget):
    """Composite widget: shows current hotkey + a Record button."""

    def __init__(self, initial: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec: str = initial
        self._recording: bool = False
        # Tokens currently physically held during a recording session.
        self._held: set[str] = set()
        # Largest combo of modifiers held simultaneously this session — what
        # we commit if the user releases without pressing a non-modifier.
        self._max_modifier_combo: list[str] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(humanize(initial))
        self._label.setStyleSheet(
            "padding: 4px 8px; border: 1px solid #888; border-radius: 4px;"
            "background: palette(base);"
        )
        self._label.setMinimumWidth(180)
        self._button = QPushButton("Record…")
        self._button.clicked.connect(self._start_recording)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._button)

    # ----- public API used by the dialog ------------------------------

    def value(self) -> str:
        return self._spec

    def set_value(self, spec: str) -> None:
        self._spec = spec
        self._label.setText(humanize(spec))

    # ----- recording state machine ------------------------------------

    def _start_recording(self) -> None:
        self._recording = True
        self._held = set()
        self._max_modifier_combo = []
        self._button.setText("Press hotkey… (Esc cancels)")
        self._button.setEnabled(False)
        self._label.setText("Listening…")
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.grabKeyboard()

    def _stop_recording(self) -> None:
        self._recording = False
        self._held = set()
        self._max_modifier_combo = []
        self._button.setText("Record…")
        self._button.setEnabled(True)
        self.releaseKeyboard()

    def _commit(self, spec: str) -> None:
        self._spec = spec
        self._label.setText(humanize(spec))
        self._stop_recording()

    def _token_for(self, event: QKeyEvent) -> tuple[str, bool] | None:
        """Return (spec_token, is_modifier) for an event, or None if unmappable."""
        vk = event.nativeVirtualKey()
        name = _MAC_VK_NAMES.get(vk)
        if name is not None:
            return f"<{name}>", vk in _MAC_MODIFIER_VKS
        text = event.text()
        if text and len(text) == 1 and text.isprintable() and not text.isspace():
            return text.lower(), False
        return None

    # ----- Qt key handling --------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt name)
        if not self._recording:
            super().keyPressEvent(event)
            return
        if event.isAutoRepeat():
            return
        if event.key() == Qt.Key.Key_Escape and not self._held:
            self._stop_recording()
            return

        mapped = self._token_for(event)
        if mapped is None:
            return
        token, is_modifier = mapped

        if not is_modifier:
            mods = list(self._max_modifier_combo)
            self._commit("+".join(mods + [token]))
            return

        if token not in self._held:
            self._held.add(token)
            if token not in self._max_modifier_combo:
                self._max_modifier_combo.append(token)
        self._label.setText(" + ".join(humanize(t) for t in self._max_modifier_combo) + " …")

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not self._recording:
            super().keyReleaseEvent(event)
            return
        if event.isAutoRepeat():
            return

        mapped = self._token_for(event)
        if mapped is None:
            return
        token, is_modifier = mapped
        if not is_modifier:
            return

        self._held.discard(token)
        # All modifiers released and the user never pressed a real key:
        # commit the modifier-only combo as the hotkey.
        if not self._held and self._max_modifier_combo:
            self._commit("+".join(self._max_modifier_combo))
