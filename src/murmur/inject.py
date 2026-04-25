"""Place transcribed text in front of the user.

Two modes:
- `to_clipboard(text)`: copy only. User has to ⌘V themselves.
- `paste_at_cursor(text)`: copy + simulate ⌘V (Ctrl-V on Linux/Windows) so the
  text lands at the focused cursor with no manual step.

The keystroke simulation uses pynput's keyboard.Controller. On macOS this
requires Accessibility permission (System Settings → Privacy & Security →
Accessibility). If permission is missing, the keystroke silently no-ops; the
text is still on the clipboard, so the user can paste manually.
"""
from __future__ import annotations

import platform
import time

import pyperclip

from ._logging import get_logger

_log = get_logger("inject")


def to_clipboard(text: str) -> bool:
    if not text:
        return False
    try:
        pyperclip.copy(text)
        return True
    except pyperclip.PyperclipException:
        _log.exception("pyperclip.copy failed")
        return False


def paste_at_cursor(text: str) -> bool:
    """Copy `text` to the clipboard, then send the platform paste shortcut.

    Returns True if both the copy and the keystroke succeeded.
    """
    if not text:
        return False
    if not to_clipboard(text):
        return False

    # Tiny delay: pasteboard writes on macOS are eventually-consistent, and
    # apps polling on focus events sometimes read the *previous* clipboard if
    # we send ⌘V immediately.
    time.sleep(0.05)

    try:
        from pynput.keyboard import Controller, Key
    except Exception:
        _log.exception("pynput keyboard import failed; clipboard-only fallback")
        return False

    try:
        modifier = Key.cmd if platform.system() == "Darwin" else Key.ctrl
        kb = Controller()
        with kb.pressed(modifier):
            kb.press("v")
            kb.release("v")
        _log.info("auto-pasted %d chars at cursor", len(text))
        return True
    except Exception:
        # Most common cause on macOS: Accessibility permission missing for the
        # bundle. Text is still on the clipboard, user can ⌘V manually.
        _log.exception("paste keystroke failed; clipboard-only fallback")
        return False
