"""Place transcribed text in front of the user.

Two modes:
- `to_clipboard(text)`: copy only. User has to ⌘V themselves.
- `paste_at_cursor(text)`: copy + simulate ⌘V (Ctrl-V on Linux/Windows) so the
  text lands at the focused cursor with no manual step.

macOS path: post CGEvents directly via ctypes against CoreGraphics. We tried
two alternatives that didn't work:

  1. pynput.keyboard.Controller — crashes the whole process at the native
     layer (no Python traceback) when called from a worker thread while the
     hotkey's pynput keyboard.Listener is also active. Same-process
     Listener/Controller reentrancy in pynput's Quartz bridge.
  2. osascript "tell System Events to keystroke v" — exits 0 from a
     LSUIElement (menu-bar) bundle, but the keystroke is silently dropped
     when macOS's Automation permission for the bundle hasn't been granted
     against System Events. That permission's prompt is unreliable for
     menu-bar apps; users rarely see it.

Direct CGEventPost only needs Accessibility (which we already check at
startup), runs entirely in-process with no pynput state involved, and posts
the event into the HID stream so it reaches whatever app is frontmost — the
same path a real keyboard takes.

Linux/Windows: keep pynput. The listener-vs-controller crash is mac-only.
"""
from __future__ import annotations

import ctypes
import platform
import time

import pyperclip

from ._logging import get_logger

_log = get_logger("inject")

# Carbon virtual key code for "v"
_KEY_V = 9
# CGEventFlags: command modifier
_CMD_FLAG = 0x100000
# CGEventTapLocation: kCGAnnotatedSessionEventTap — events are routed
# through the user-session event router, which targets the frontmost app
# reliably for synthetic input. HID tap (0) sometimes silently drops
# synthetic events from ad-hoc signed bundles on recent macOS.
_SESSION_TAP = 2
# kCGKeyboardEventAutorepeat — integer field on a keyboard event. macOS
# sets this on synthesized repeats; many apps ignore auto-repeat for
# shortcut chords like ⌘V, so we must explicitly mark every event we
# post as 0 (a fresh press, not a repeat).
_AUTOREPEAT_FIELD = 8
# CGEventType: kCGEventFlagsChanged — emitted by macOS whenever a
# modifier key transitions. Posting one with flags=0 declares "no
# modifiers held" to the OS, clearing any stuck modifier state left
# over from the user's hotkey release.
_FLAGS_CHANGED = 12


def to_clipboard(text: str) -> bool:
    if not text:
        return False
    try:
        pyperclip.copy(text)
        return True
    except pyperclip.PyperclipException:
        _log.exception("pyperclip.copy failed")
        return False


def _paste_macos() -> bool:
    """Post ⌘V into the HID event stream via CoreGraphics."""
    try:
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cf = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
    except OSError:
        _log.exception("CoreGraphics not available")
        return False

    cg.CGEventCreate.restype = ctypes.c_void_p
    cg.CGEventCreate.argtypes = [ctypes.c_void_p]
    cg.CGEventSetType.restype = None
    cg.CGEventSetType.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    cg.CGEventCreateKeyboardEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint16,
        ctypes.c_bool,
    ]
    cg.CGEventSetFlags.restype = None
    cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    cg.CGEventSetIntegerValueField.restype = None
    cg.CGEventSetIntegerValueField.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int64,
    ]
    cg.CGEventPost.restype = None
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    cf.CFRelease.restype = None
    cf.CFRelease.argtypes = [ctypes.c_void_p]

    # Reset OS modifier state before our ⌘V. The user's hotkey is often a
    # modifier itself (default <right_alt> = Right Option, a dead-key
    # modifier on macOS). When pynput's listener processes the release, OS
    # modifier state can stay sticky for ~1s afterward — making our
    # subsequent synthetic ⌘V parse as ⌥⌘V (or worse) at the receiving app.
    # Symptom: the system "no can do" beep, no paste. A flagsChanged event
    # with flags=0 declares "no modifiers held" and clears the sticky bits.
    flush = cg.CGEventCreate(None)
    if flush:
        cg.CGEventSetType(flush, _FLAGS_CHANGED)
        cg.CGEventSetFlags(flush, 0)
        cg.CGEventPost(_SESSION_TAP, flush)
        cf.CFRelease(flush)

    # NULL source: empirically the only source flavor where the first paste
    # actually lands from this ad-hoc-signed bundle. Combined-session and
    # HID-system sources both fail TCC's synthetic-input filter on Sonoma+.
    # We deliberately do NOT post separate Cmd-down/Cmd-up events: those
    # are picked up by our hotkey's pynput.Listener (which sits on the
    # same event tap chain) and creating a fresh Listener afterwards
    # crashes pynput's macOS bridge.
    #
    # Cmd flag on BOTH events: the ⌘ must remain held across the v-down /
    # v-up pair or the receiving app sees plain "v". Plus autorepeat=0 on
    # both: macOS marks repeated synthesized presses as auto-repeats and
    # apps like Terminal silently drop auto-repeat ⌘V; the symptom is
    # "first paste lands, every subsequent one disappears."
    for key_down in (True, False):
        ev = cg.CGEventCreateKeyboardEvent(None, _KEY_V, key_down)
        if not ev:
            _log.error("CGEventCreateKeyboardEvent returned NULL (down=%s)", key_down)
            return False
        cg.CGEventSetFlags(ev, _CMD_FLAG)
        cg.CGEventSetIntegerValueField(ev, _AUTOREPEAT_FIELD, 0)
        cg.CGEventPost(_SESSION_TAP, ev)
        cf.CFRelease(ev)
        if key_down:
            time.sleep(0.01)
    return True


def _paste_pynput() -> bool:
    """Linux/Windows path: simulate Ctrl-V via pynput."""
    try:
        from pynput.keyboard import Controller, Key
    except Exception:
        _log.exception("pynput keyboard import failed; clipboard-only fallback")
        return False
    try:
        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.press("v")
            kb.release("v")
        return True
    except Exception:
        _log.exception("paste keystroke failed; clipboard-only fallback")
        return False


def paste_at_cursor(text: str) -> bool:
    """Copy `text` to the clipboard, then send the platform paste shortcut.

    Returns True if both the copy and the keystroke succeeded. On macOS, if
    Accessibility isn't granted we skip the keystroke and stay clipboard-only
    — osascript would just fail with a permission error anyway, and the text
    is already on the clipboard so the user can paste manually.
    """
    if not text:
        return False
    if not to_clipboard(text):
        return False

    if platform.system() == "Darwin":
        from .permissions import AccessibilityStatus, accessibility_status

        if accessibility_status() != AccessibilityStatus.GRANTED:
            _log.warning(
                "Accessibility not granted; skipping ⌘V keystroke. "
                "Text is on the clipboard — paste manually with ⌘V, or grant "
                "Accessibility in System Settings → Privacy & Security."
            )
            return False

    # Pasteboard writes on macOS are eventually-consistent — apps polling on
    # focus events sometimes read the *previous* clipboard if we paste
    # immediately. A small delay avoids that race.
    time.sleep(0.05)

    ok = _paste_macos() if platform.system() == "Darwin" else _paste_pynput()
    if ok:
        _log.info("auto-pasted %d chars at cursor", len(text))
    return ok
