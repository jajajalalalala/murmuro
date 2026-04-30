"""Smoke tests for the restart helper.

The user-visible restart flow is now a modal in ``main_window``
(:meth:`MainWindow._prompt_restart_for_hotkey`) — see #38. This module
just provides the ``os.execv`` call the modal fires when the user clicks
Restart. We test the call shape (not the actual exec).
"""
from __future__ import annotations

import sys
from unittest.mock import patch

from murmur.restart import _default_relaunch


def test_default_relaunch_invokes_execv_with_sys_argv():
    """`_default_relaunch` must hand `sys.executable` + the original
    argv to `os.execv`. Both `python -m murmur` and the PyInstaller
    bundle rely on this shape — see the function's comment."""
    with (
        patch("murmur.restart.os.execv") as execv_mock,
        patch("murmur.restart.QApplication.instance", return_value=None),
    ):
        _default_relaunch()

    execv_mock.assert_called_once_with(
        sys.executable, [sys.executable, *sys.argv]
    )


def test_default_relaunch_quits_qapplication_first_when_present():
    """When a QApplication is alive we ask it to quit before exec'ing —
    lets Qt run any cleanup it needs (released sockets, etc.)."""
    fake_app = type("FakeApp", (), {"quit_called": False})
    fake_app.quit = lambda self=fake_app: setattr(fake_app, "quit_called", True)

    with (
        patch("murmur.restart.os.execv") as execv_mock,
        patch("murmur.restart.QApplication.instance", return_value=fake_app),
    ):
        _default_relaunch()

    assert fake_app.quit_called is True
    execv_mock.assert_called_once()
