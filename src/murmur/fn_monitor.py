"""macOS Fn-key global monitor.

pynput's macOS Listener doesn't surface the Fn key — the OS reports it
through ``flagsChanged`` events with ``NSEventModifierFlagFunction``
(0x800000), which pynput's CGEvent tap filters out. To let users bind
``<fn>`` as a push-to-talk hotkey we attach a parallel NSEvent global
monitor and synthesize press / release callbacks ourselves.

The monitor only watches Fn — every other modifier still goes through
pynput. It's a side channel, not a replacement.

This module is a no-op on non-macOS platforms; ``FnMonitor.start`` simply
returns without registering anything so callers don't need to platform-
gate.
"""
from __future__ import annotations

import sys
from collections.abc import Callable

from ._logging import get_logger

_log = get_logger("fn_monitor")

# NSEventModifierFlagFunction — set when Fn is currently held.
NS_FN_FLAG = 1 << 23  # 0x800000


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
        self._is_down = False

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

        def _handler(event):
            try:
                flags = event.modifierFlags()
                is_down = bool(flags & NS_FN_FLAG)
                if is_down and not self._is_down:
                    self._is_down = True
                    self._on_press()
                elif not is_down and self._is_down:
                    self._is_down = False
                    self._on_release()
            except Exception:  # noqa: BLE001
                _log.exception("FnMonitor handler raised")

        self._handler = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskFlagsChanged, _handler
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
        self._is_down = False
