"""Global push-to-talk hotkey via pynput.

The hotkey is *held* — `on_press` fires once when the key goes down,
`on_release` fires when it comes back up. Modifier-only hotkeys
(e.g. <right_alt>, <ctrl>) work fine; combo hotkeys are also supported.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable

from pynput import keyboard


class PushToTalkHotkey:
    """Listen for one specific key/combo and call on_press/on_release.

    `key_spec` follows pynput's syntax:
      - "<right_alt>", "<ctrl>", "<f9>" — single modifier/special
      - "<ctrl>+<shift>+<space>" — combo
      - "a" — plain letter (rarely useful for push-to-talk)
    """

    def __init__(
        self,
        key_spec: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._key_spec = key_spec
        self._on_press = on_press
        self._on_release = on_release
        self._target_keys = self._parse_keys(key_spec)
        self._listener: keyboard.Listener | None = None
        self._held_keys: set = set()
        self._is_active = False  # True while the chord is fully held

    # Friendly names → pynput Key attribute names. pynput uses `alt_r`, `cmd_l`,
    # etc., but humans (and the README) say "right_alt" / "right_option".
    KEY_ALIASES = {
        "right_alt": "alt_r",
        "left_alt": "alt_l",
        "right_option": "alt_r",
        "left_option": "alt_l",
        "option": "alt",
        "right_ctrl": "ctrl_r",
        "left_ctrl": "ctrl_l",
        "control": "ctrl",
        "right_shift": "shift_r",
        "left_shift": "shift_l",
        "right_cmd": "cmd_r",
        "left_cmd": "cmd_l",
        "right_command": "cmd_r",
        "left_command": "cmd_l",
        "command": "cmd",
        "meta": "cmd",
        "right_meta": "cmd_r",
        "left_meta": "cmd_l",
        "return": "enter",
        "escape": "esc",
    }

    @classmethod
    def _parse_keys(cls, spec: str) -> set:
        """Parse a hotkey spec into a set of pynput Key/KeyCode objects."""
        out = set()
        for token in spec.split("+"):
            token = token.strip()
            if token.startswith("<") and token.endswith(">"):
                name = token[1:-1].lower()
                name = cls.KEY_ALIASES.get(name, name)
                key = getattr(keyboard.Key, name, None)
                if key is None:
                    raise ValueError(f"Unknown special key: {token}")
                out.add(key)
            elif len(token) == 1:
                out.add(keyboard.KeyCode.from_char(token))
            else:
                raise ValueError(f"Cannot parse hotkey token: {token!r}")
        return out

    def _normalize(self, key) -> object:
        # Treat left/right modifier variants as their generic form when the spec
        # asked for the generic one, and vice-versa.
        if isinstance(key, keyboard.Key):
            return key
        return key

    def _on_key_press(self, key) -> None:
        key = self._normalize(key)
        if key in self._target_keys:
            self._held_keys.add(key)
            if not self._is_active and self._held_keys >= self._target_keys:
                self._is_active = True
                with contextlib.suppress(Exception):
                    self._on_press()

    def _on_key_release(self, key) -> None:
        key = self._normalize(key)
        if key in self._target_keys:
            self._held_keys.discard(key)
            if self._is_active and not (self._held_keys >= self._target_keys):
                self._is_active = False
                with contextlib.suppress(Exception):
                    self._on_release()

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
