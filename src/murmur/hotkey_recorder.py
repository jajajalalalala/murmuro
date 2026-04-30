"""Click-to-record widget for capturing a hotkey by pressing it.

The user clicks "Record", presses the desired key (or combo) once, and the
widget commits the result in pynput-compatible spec form
(e.g. ``<right_alt>``, ``<ctrl>+<shift>+<space>``, ``<f9>``, ``a``,
``<left_ctrl>+5``). The committed spec is what
:func:`murmur.hotkey.PushToTalkHotkey._parse_keys` already understands.

Single-modifier hotkeys (Right Option alone) are detected on key release
once the user lets go of the last modifier; combos with a non-modifier
key (Ctrl+Shift+Space) commit on the non-modifier press.

The macOS virtual-keycode tables below cover every key on a standard
Apple keyboard: full F-row (F1–F20), navigation cluster, arrows, the
keypad, and every printable character — so users can build hotkeys
around any physical key without falling back to "edit the TOML".
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .fn_monitor import FnFocusMonitor

# ─────────────────────────────────────────────────────────────────────────────
# macOS virtual keycodes
# ─────────────────────────────────────────────────────────────────────────────
# Source: <Carbon/HIToolbox/Events.h> kVK_* constants.
# Values are stable across hardware; layout-dependent characters (e.g. ;) are
# intentionally NOT pulled from event.text() because Shift+; would otherwise
# commit as ":". Instead we record the *physical* key by VK.

# VK → pynput special-key name (rendered as "<name>" in the spec).
# Every name listed here must resolve to a real ``pynput.keyboard.Key``
# member after :data:`murmur.hotkey.PushToTalkHotkey.KEY_ALIASES` is
# applied — otherwise the listener can't bind it. ``fn`` is deliberately
# absent until the NSEvent-global-monitor side channel lands.
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
    0x39: "caps_lock",
    0x3F: "fn",  # captured via NSEvent global monitor (see fn_monitor.py)
    # Function row
    0x7A: "f1", 0x78: "f2", 0x63: "f3", 0x76: "f4",
    0x60: "f5", 0x61: "f6", 0x62: "f7", 0x64: "f8",
    0x65: "f9", 0x6D: "f10", 0x67: "f11", 0x6F: "f12",
    0x69: "f13", 0x6B: "f14", 0x71: "f15", 0x6A: "f16",
    0x40: "f17", 0x4F: "f18", 0x50: "f19", 0x5A: "f20",
    # Whitespace / control
    0x31: "space", 0x30: "tab", 0x35: "esc", 0x24: "enter",
    0x33: "backspace", 0x75: "delete",
    # Navigation cluster
    0x73: "home", 0x77: "end", 0x74: "page_up", 0x79: "page_down",
    # Arrows
    0x7B: "left", 0x7C: "right", 0x7D: "down", 0x7E: "up",
}

# VK → unshifted printable character (US QWERTY).
# Used so Shift+5 commits as "5" (the physical key) rather than "%".
# Keypad VKs collapse to the matching glyph so users can hold a numpad
# digit/symbol as a hotkey component without a separate spec syntax.
_MAC_VK_CHARS: dict[int, str] = {
    # Letters
    0x00: "a", 0x0B: "b", 0x08: "c", 0x02: "d", 0x0E: "e", 0x03: "f",
    0x05: "g", 0x04: "h", 0x22: "i", 0x26: "j", 0x28: "k", 0x25: "l",
    0x2E: "m", 0x2D: "n", 0x1F: "o", 0x23: "p", 0x0C: "q", 0x0F: "r",
    0x01: "s", 0x11: "t", 0x20: "u", 0x09: "v", 0x0D: "w", 0x07: "x",
    0x10: "y", 0x06: "z",
    # Top-row digits
    0x12: "1", 0x13: "2", 0x14: "3", 0x15: "4", 0x17: "5",
    0x16: "6", 0x1A: "7", 0x1C: "8", 0x19: "9", 0x1D: "0",
    # Punctuation
    0x1B: "-", 0x18: "=", 0x21: "[", 0x1E: "]", 0x2A: "\\",
    0x29: ";", 0x27: "'", 0x2B: ",", 0x2F: ".", 0x2C: "/",
    0x32: "`",
    # Keypad (collapse to top-row equivalents)
    0x52: "0", 0x53: "1", 0x54: "2", 0x55: "3", 0x56: "4",
    0x57: "5", 0x58: "6", 0x59: "7", 0x5B: "8", 0x5C: "9",
    0x41: ".", 0x4E: "-", 0x45: "+", 0x4B: "/", 0x51: "=",
}

_MAC_MODIFIER_VKS: frozenset[int] = frozenset({
    0x37, 0x36, 0x38, 0x3C, 0x3A, 0x3D, 0x3B, 0x3E, 0x39, 0x3F,
})


# Friendly display labels for the spec-token humanizer. Keys are spec-token
# names ("right_alt", "page_up", "kp_0", "f1", ...). Anything missing falls
# back to a sensible default in :func:`humanize`.
_HUMAN_NAMES: dict[str, str] = {
    "right_alt": "Right Option",
    "left_alt": "Left Option",
    "right_cmd": "Right Command",
    "left_cmd": "Left Command",
    "right_shift": "Right Shift",
    "left_shift": "Left Shift",
    "right_ctrl": "Right Control",
    "left_ctrl": "Left Control",
    "caps_lock": "Caps Lock",
    "fn": "Fn",
    "space": "Space", "tab": "Tab", "esc": "Esc", "enter": "Return",
    "backspace": "Delete",   # the key labelled "delete" on Apple keyboards
    "delete": "Forward Delete",
    "home": "Home", "end": "End",
    "page_up": "Page Up", "page_down": "Page Down",
    "left": "←", "right": "→", "up": "↑", "down": "↓",
}


def resolve_key_event(event: QKeyEvent) -> tuple[str, bool] | None:
    """Resolve a Qt key event to ``(spec_token, is_modifier)``, or ``None``.

    Resolution order: macOS VK→name table, then VK→char table, then
    ``event.text()``. Shared by :class:`HotkeyRecorder` and the live
    key-probe widget on the Shortcuts page so both interpret physical
    keys identically.
    """
    vk = event.nativeVirtualKey()
    name = _MAC_VK_NAMES.get(vk)
    if name is not None:
        return f"<{name}>", vk in _MAC_MODIFIER_VKS
    char = _MAC_VK_CHARS.get(vk)
    if char is not None:
        return char, False
    text = event.text()
    if text and len(text) == 1 and text.isprintable() and not text.isspace():
        return text.lower(), False
    return None


def humanize(spec: str) -> str:
    """Turn a pynput spec into something readable in the dialog."""
    if not spec:
        return "(none)"
    parts = spec.split("+")
    pretty: list[str] = []
    for raw in parts:
        token = raw.strip()
        if token.startswith("<") and token.endswith(">"):
            name = token[1:-1]
            if name in _HUMAN_NAMES:
                pretty.append(_HUMAN_NAMES[name])
            elif name.startswith("f") and name[1:].isdigit():
                pretty.append(name.upper())
            elif name.startswith("kp_"):
                pretty.append("Num " + name[3:].title())
            else:
                pretty.append(name.replace("_", " ").title())
        else:
            pretty.append(token.upper())
    return " + ".join(pretty)


class HotkeyRecorder(QWidget):
    """Composite widget: shows current hotkey + a Record button.

    Emits ``value_changed(spec)`` whenever the user records a new combo.
    Programmatic ``set_value`` is intentionally silent so external config
    reloads (e.g. user hand-edits the TOML) don't bounce back through
    the page's persistence path.
    """

    value_changed = Signal(str)

    def __init__(self, initial: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec: str = initial
        self._recording: bool = False
        # Tokens currently physically held during a recording session.
        self._held: set[str] = set()
        # Largest combo of modifiers held simultaneously this session — what
        # we commit if the user releases without pressing a non-modifier.
        self._max_modifier_combo: list[str] = []
        # Side-channel monitor for the Fn (🌐) key. Cocoa never delivers
        # ``keyDown:`` for Fn — only ``flagsChanged:`` — so Qt's
        # ``keyPressEvent`` never fires for it. Without this monitor the
        # recorder waits forever when the user presses Fn. Installed only
        # while a recording session is active. See fn_monitor.py.
        self._fn_monitor = FnFocusMonitor(
            on_press=self._on_fn_press,
            on_release=self._on_fn_release,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._label = QLabel(humanize(initial))
        self._label.setStyleSheet(
            "padding: 6px 10px; border: 1px solid palette(mid);"
            "border-radius: 6px; background: palette(base);"
        )
        self._label.setMinimumWidth(180)
        self._button = QPushButton("Record…")
        self._button.setProperty("primary", True)
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
        # Arm the Fn-key side channel for this session. No-op off-macOS.
        self._fn_monitor.start()

    def _stop_recording(self) -> None:
        self._recording = False
        self._held = set()
        self._max_modifier_combo = []
        self._button.setText("Record…")
        self._button.setEnabled(True)
        self.releaseKeyboard()
        # Tear down the Fn monitor so we don't leak NSEvent handlers
        # across record sessions.
        self._fn_monitor.stop()

    def _commit(self, spec: str) -> None:
        self._spec = spec
        self._label.setText(humanize(spec))
        self._stop_recording()
        self.value_changed.emit(spec)

    def _token_for(self, event: QKeyEvent) -> tuple[str, bool] | None:
        return resolve_key_event(event)

    # ----- Fn side channel (NSEvent flagsChanged) ---------------------
    # Cocoa doesn't deliver keyDown:/keyUp: for Fn — only flagsChanged:.
    # The FnFocusMonitor turns those flag transitions into edge-triggered
    # callbacks that drive the same state machine as Qt key events.

    def _on_fn_press(self) -> None:
        if not self._recording:
            return
        token = "<fn>"
        if token not in self._held:
            self._held.add(token)
            if token not in self._max_modifier_combo:
                self._max_modifier_combo.append(token)
        self._label.setText(
            " + ".join(humanize(t) for t in self._max_modifier_combo) + " …"
        )

    def _on_fn_release(self) -> None:
        if not self._recording:
            return
        token = "<fn>"
        self._held.discard(token)
        if not self._held and self._max_modifier_combo:
            self._commit("+".join(self._max_modifier_combo))

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
