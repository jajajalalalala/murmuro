"""Permission helpers — mostly that they import cleanly and behave on non-mac."""
from __future__ import annotations

import platform

from murmur.permissions import (
    IS_MAC,
    InputMonitoringStatus,
    input_monitoring_status,
    open_input_monitoring_settings,
    request_input_monitoring,
)


def test_is_mac_matches_platform():
    assert (platform.system() == "Darwin") == IS_MAC


def test_status_returns_known_enum():
    s = input_monitoring_status()
    assert isinstance(s, InputMonitoringStatus)


def test_request_is_safe_to_call_on_non_mac():
    if IS_MAC:
        return  # we don't want to actually trigger the system prompt in CI
    assert request_input_monitoring() is False


def test_open_settings_is_safe_to_call_on_non_mac():
    if IS_MAC:
        return  # don't pop System Settings during a test run
    open_input_monitoring_settings()  # no-op on non-mac
