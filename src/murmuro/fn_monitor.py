"""macOS Fn-key NSEvent monitors.

pynput's macOS Listener doesn't surface the Fn key — the OS reports it
through ``flagsChanged`` events with ``NSEventModifierFlagFunction``
(0x800000), which pynput's CGEvent tap filters out. Qt is no better:
``QWidget.keyPressEvent`` is fed from Cocoa's ``keyDown:`` callback,
which never fires for Fn either. To let users *bind* and *use* ``<fn>``
as a push-to-talk hotkey we attach parallel NSEvent monitors and
synthesize press / release callbacks ourselves.

This module exposes two thin classes:

* :class:`FnMonitor` — global monitor used at runtime, after a hotkey
  has been committed, so Fn fires the listener regardless of which app
  has focus.
* :class:`FnFocusMonitor` — local monitor scoped to a focused widget,
  used by the click-to-record UI and the Shortcuts page key-probe so the
  user can actually capture Fn in the first place.

Both wrap the same flagsChanged dispatch and only watch Fn — every other
modifier still goes through pynput / Qt. They're side channels, not
replacements.

Both classes are no-ops on non-macOS platforms; ``start`` simply returns
``False`` without registering anything so callers don't need to
platform-gate.
"""
from __future__ import annotations

import sys
from collections.abc import Callable

from ._logging import get_logger

_log = get_logger("fn_monitor")

# NSEventModifierFlagFunction — set when Fn is currently held.
NS_FN_FLAG = 1 << 23  # 0x800000


def _make_flags_handler(
    on_press: Callable[[], None],
    on_release: Callable[[], None],
    state: dict,
    label: str,
):
    """Build a flagsChanged handler that emits edge-triggered Fn callbacks.

    ``state`` is a one-key dict (``{"down": bool}``) so the closure can
    mutate it without ``nonlocal`` gymnastics, which keeps the global
    and local monitor implementations symmetric.
    """
    def handler(event):
        try:
            flags = event.modifierFlags()
            is_down = bool(flags & NS_FN_FLAG)
            if is_down and not state["down"]:
                state["down"] = True
                on_press()
            elif not is_down and state["down"]:
                state["down"] = False
                on_release()
        except Exception:  # noqa: BLE001
            _log.exception("%s handler raised", label)
        # Local monitors must return the event (or None to swallow it).
        # Global monitors ignore the return value, so always returning
        # the event is safe for both.
        return event
    return handler


class FnMonitor:
    """Edge-triggered Fn-key callbacks via NSEvent global monitor.

    ``on_press`` fires once when the Fn key transitions from up to down,
    ``on_release`` once when it goes back up. The monitor is global —
    works regardless of which app has focus — but requires the same
    macOS Input Monitoring grant pynput already needs.
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._handler = None  # the opaque token NSEvent returns
        self._state = {"down": False}

    def start(self) -> bool:
        """Register the global monitor. Returns False on non-macOS or if
        registration fails (typically because pyobjc isn't installed)."""
        if sys.platform != "darwin":
            return False
        try:
            from AppKit import NSEvent, NSEventMaskFlagsChanged
        except ImportError:
            _log.warning("AppKit not available; Fn key won't be bindable")
            return False

        handler = _make_flags_handler(
            self._on_press, self._on_release, self._state, "FnMonitor"
        )
        self._handler = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskFlagsChanged, handler
        )
        if self._handler is None:
            _log.warning("addGlobalMonitorForEventsMatchingMask returned nil")
            return False
        _log.info("Fn global monitor armed (handler=%r)", self._handler)
        return True

    def stop(self) -> None:
        if self._handler is None:
            return
        try:
            from AppKit import NSEvent
            NSEvent.removeMonitor_(self._handler)
        except Exception:  # noqa: BLE001
            _log.exception("removeMonitor_ failed")
        self._handler = None
        self._state["down"] = False


class FnFocusMonitor:
    """Edge-triggered Fn-key callbacks via NSEvent **local** monitor.

    Used by widgets that need to capture Fn while focused (the recorder
    dialog, the key probe). Lifetime matches the widget's focus: install
    on ``focusInEvent``, tear down on ``focusOutEvent`` and on any
    successful commit so we don't leak NSEvent handlers across focus
    cycles.
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._handler = None
        self._state = {"down": False}

    def start(self) -> bool:
        if sys.platform != "darwin":
            return False
        try:
            from AppKit import NSEvent, NSEventMaskFlagsChanged
        except ImportError:
            _log.warning("AppKit not available; Fn key not capturable in UI")
            return False

        handler = _make_flags_handler(
            self._on_press, self._on_release, self._state, "FnFocusMonitor"
        )
        self._handler = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskFlagsChanged, handler
        )
        if self._handler is None:
            _log.warning("addLocalMonitorForEventsMatchingMask returned nil")
            return False
        return True

    def stop(self) -> None:
        if self._handler is None:
            return
        try:
            from AppKit import NSEvent
            NSEvent.removeMonitor_(self._handler)
        except Exception:  # noqa: BLE001
            _log.exception("removeMonitor_ failed")
        self._handler = None
        self._state["down"] = False
