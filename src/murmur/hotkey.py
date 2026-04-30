"""Global push-to-talk hotkey via pynput.

The hotkey is *held* — `on_press` fires once when the key goes down,
`on_release` fires when it comes back up. Modifier-only hotkeys
(e.g. <right_alt>, <ctrl>) work fine; combo hotkeys are also supported.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from pynput import keyboard

from ._logging import get_logger
from .fn_monitor import FnMonitor

_log = get_logger("hotkey")


class _FnSentinel:
    """Stand-in for the macOS Fn key in target/held key sets.

    pynput has no Key.fn enum on macOS, so we represent it with a hashable
    singleton and route press/release notifications from
    :class:`FnMonitor` through the same code path as pynput keys.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<fn>"


FN_KEY = _FnSentinel()


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
        self._fn_monitor: FnMonitor | None = None
        self._held_keys: set = set()
        self._is_active = False  # True while the chord is fully held
        # Guards in-place rebinds (replace_spec) against concurrent reads
        # from the listener thread. The listener fires _on_key_press /
        # _on_key_release on its own thread, so a naive swap of
        # _target_keys could race with a comparison mid-event.
        self._lock = threading.Lock()

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
        """Parse a hotkey spec into a set of pynput Key/KeyCode objects.

        ``<fn>`` is special — there is no pynput Key for it on macOS, so
        we substitute :data:`FN_KEY`, a sentinel the listener routes
        press/release events through alongside pynput's keys (see
        :class:`murmur.fn_monitor.FnMonitor`).
        """
        out = set()
        for token in spec.split("+"):
            token = token.strip()
            if token.startswith("<") and token.endswith(">"):
                name = token[1:-1].lower()
                if name == "fn":
                    out.add(FN_KEY)
                    continue
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

    def _key_repr(self, key) -> str:
        if isinstance(key, keyboard.Key):
            return f"<{key.name}>"
        try:
            return repr(key.char)
        except AttributeError:
            return repr(key)

    def _on_key_press(self, key) -> None:
        try:
            _log.debug("press  %s", self._key_repr(key))
            with self._lock:
                if key not in self._target_keys:
                    return
                self._held_keys.add(key)
                activated = (
                    not self._is_active
                    and self._held_keys >= self._target_keys
                )
                if activated:
                    self._is_active = True
                    spec = self._key_spec
            if activated:
                _log.info("hotkey ACTIVATED (%s)", spec)
                try:
                    self._on_press()
                except Exception:
                    _log.exception("on_press callback raised")
        except Exception:
            _log.exception("error in _on_key_press")

    def _on_key_release(self, key) -> None:
        try:
            _log.debug("release %s", self._key_repr(key))
            with self._lock:
                if key not in self._target_keys:
                    return
                self._held_keys.discard(key)
                released = (
                    self._is_active
                    and not (self._held_keys >= self._target_keys)
                )
                if released:
                    self._is_active = False
                    spec = self._key_spec
            if released:
                _log.info("hotkey RELEASED (%s)", spec)
                try:
                    self._on_release()
                except Exception:
                    _log.exception("on_release callback raised")
        except Exception:
            _log.exception("error in _on_key_release")

    def start(self) -> None:
        if self._listener is not None:
            return
        target_names = sorted(self._key_repr(k) for k in self._target_keys)
        _log.info("starting pynput Listener for %s -> %s", self._key_spec, target_names)
        self._listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._listener.daemon = True
        self._listener.start()

        # Spawn a watcher: if the listener thread dies (e.g. macOS denies the
        # event tap), we want it in the log instead of staying silent forever.
        threading.Thread(
            target=self._watch_listener,
            name="murmur-hotkey-watch",
            daemon=True,
        ).start()

        # Side channel for the macOS Fn key: pynput can't see flagsChanged
        # for NSEventModifierFlagFunction, so we attach our own NSEvent
        # global monitor and forward press/release events through the same
        # held-keys logic by passing FN_KEY.
        if FN_KEY in self._target_keys:
            self._fn_monitor = FnMonitor(
                on_press=lambda: self._on_key_press(FN_KEY),
                on_release=lambda: self._on_key_release(FN_KEY),
            )
            ok = self._fn_monitor.start()
            if not ok:
                _log.warning("Fn monitor not armed; <fn> hotkey will not fire")

    def _watch_listener(self) -> None:
        listener = self._listener
        if listener is None:
            return
        # Give it a moment to come up, then check it's actually alive.
        time.sleep(0.5)
        if not listener.running:
            _log.error(
                "pynput Listener failed to start — likely macOS Input Monitoring "
                "is not granted to this binary. Toggle it OFF then ON in "
                "System Settings → Privacy & Security → Input Monitoring."
            )
            return
        _log.info("pynput Listener is running")
        # If it dies later, log that too.
        listener.join()
        if self._listener is listener:
            _log.warning("pynput Listener thread exited unexpectedly")

    def stop(self) -> None:
        if self._listener is not None:
            _log.info("stopping pynput Listener")
            self._listener.stop()
            self._listener = None
        if self._fn_monitor is not None:
            self._fn_monitor.stop()
            self._fn_monitor = None

    def replace_spec(self, new_spec: str) -> None:
        """Rebind to a new key spec without tearing down the listener.

        pynput's :class:`Listener` fires press/release for *every* key; we
        filter against ``_target_keys``. Swapping the target set is therefore
        enough to rebind — no event-tap teardown, no race window where the
        old and new listeners briefly fight for events. (PR #47 tried the
        stop+start dance and the old listener kept firing in production;
        this avoids the failure mode entirely.)

        ``FnMonitor`` is the one piece that needs lifecycle management: it
        attaches a separate NSEvent monitor for the macOS Fn key, which
        pynput can't see. Start it if ``<fn>`` is newly needed; stop it if
        no longer.
        """
        new_keys = self._parse_keys(new_spec)
        with self._lock:
            self._key_spec = new_spec
            self._target_keys = new_keys
            # Drop any stale held-key state from the old chord. If the user
            # was holding the previous hotkey when they hit Save, the
            # release event for it would no longer match the new target
            # set, so _held_keys would never converge back to empty.
            self._held_keys = set()
            self._is_active = False

        needs_fn = FN_KEY in new_keys
        has_fn = self._fn_monitor is not None
        if needs_fn and not has_fn:
            self._fn_monitor = FnMonitor(
                on_press=lambda: self._on_key_press(FN_KEY),
                on_release=lambda: self._on_key_release(FN_KEY),
            )
            if not self._fn_monitor.start():
                _log.warning("Fn monitor not armed; <fn> hotkey will not fire")
        elif has_fn and not needs_fn:
            self._fn_monitor.stop()
            self._fn_monitor = None
        target_names = sorted(self._key_repr(k) for k in new_keys)
        _log.info("rebound hotkey in place: %s -> %s", new_spec, target_names)
