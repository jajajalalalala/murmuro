"""macOS Input Monitoring permission helpers.

pynput's keyboard listener uses a CGEventTap, which silently fails to receive
events unless the running binary is granted **Input Monitoring** in System
Settings. We detect the state and prompt the user instead of letting the app
launch and look broken.

We talk to IOKit through ctypes so we don't pull pyobjc into the runtime deps.
"""
from __future__ import annotations

import platform
import subprocess
from enum import Enum

IS_MAC = platform.system() == "Darwin"

# IOKit's IOHIDRequestType values.
_REQUEST_TYPE_LISTEN_EVENT = 1  # kIOHIDRequestTypeListenEvent

# IOKit's IOHIDAccessType return values.
_ACCESS_GRANTED = 0
_ACCESS_UNKNOWN = 1  # never asked yet
_ACCESS_DENIED = 2


class InputMonitoringStatus(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"
    UNKNOWN = "unknown"  # not yet prompted, or non-mac
    UNAVAILABLE = "unavailable"  # IOKit symbols missing (older macOS)


def _iokit():
    import ctypes

    return ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")


def input_monitoring_status() -> InputMonitoringStatus:
    if not IS_MAC:
        return InputMonitoringStatus.UNKNOWN
    try:
        import ctypes

        iokit = _iokit()
        iokit.IOHIDCheckAccess.restype = ctypes.c_uint32
        iokit.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        code = iokit.IOHIDCheckAccess(_REQUEST_TYPE_LISTEN_EVENT)
    except (OSError, AttributeError):
        return InputMonitoringStatus.UNAVAILABLE
    return {
        _ACCESS_GRANTED: InputMonitoringStatus.GRANTED,
        _ACCESS_UNKNOWN: InputMonitoringStatus.UNKNOWN,
        _ACCESS_DENIED: InputMonitoringStatus.DENIED,
    }.get(code, InputMonitoringStatus.UNKNOWN)


def request_input_monitoring() -> bool:
    """Trigger the macOS prompt for Input Monitoring (first-time only).

    After the user responds, the binary appears in System Settings → Privacy &
    Security → Input Monitoring. Returns True if granted, False otherwise.
    Subsequent calls return the cached decision without re-prompting.
    """
    if not IS_MAC:
        return False
    try:
        import ctypes

        iokit = _iokit()
        iokit.IOHIDRequestAccess.restype = ctypes.c_bool
        iokit.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
        return bool(iokit.IOHIDRequestAccess(_REQUEST_TYPE_LISTEN_EVENT))
    except (OSError, AttributeError):
        return False


def open_input_monitoring_settings() -> None:
    """Jump the user straight to the right pane in System Settings."""
    if not IS_MAC:
        return
    subprocess.run(
        [
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
        ],
        check=False,
    )
