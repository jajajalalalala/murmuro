"""Smoke tests for the restart helper.

The user-visible restart flow is now a modal in ``main_window``
(:meth:`MainWindow._confirm_hotkey_restart`) — see #38. This module
just provides the actual relaunch the modal fires when the user clicks
Restart. We test the call shape (not the actual exec / Popen).

Two strategies live in the same function:

- macOS ``.app`` bundles use ``open -na <bundle>`` because ``os.execv``
  keeps the parent's Process Serial Number and LaunchServices silently
  refuses to register the relaunched instance.
- Dev mode (``python -m murmuro``) and any non-darwin platform fall back
  to ``os.execv``.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

from murmuro.restart import _default_relaunch, _find_app_bundle_root

# --- _find_app_bundle_root -----------------------------------------------


def test_find_bundle_returns_none_off_darwin():
    with patch.object(sys, "platform", "linux"):
        assert _find_app_bundle_root() is None


def test_find_bundle_walks_up_to_dot_app(tmp_path):
    # Lay out a fake bundle: <tmp>/Murmuro.app/Contents/MacOS/Murmuro
    bundle = tmp_path / "Murmuro.app"
    binary = bundle / "Contents" / "MacOS" / "Murmuro"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    with (
        patch.object(sys, "platform", "darwin"),
        patch.object(sys, "executable", str(binary)),
    ):
        assert _find_app_bundle_root() == str(bundle)


def test_find_bundle_returns_none_when_no_dot_app_ancestor(tmp_path):
    # Plain /usr/local/bin/python-style layout — nothing ends in .app.
    binary = tmp_path / "bin" / "python"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    with (
        patch.object(sys, "platform", "darwin"),
        patch.object(sys, "executable", str(binary)),
    ):
        assert _find_app_bundle_root() is None


# --- _default_relaunch ---------------------------------------------------


def test_default_relaunch_uses_open_for_dot_app_bundle(tmp_path):
    """In a PyInstaller .app, plain os.execv keeps the parent's Process
    Serial Number and LaunchServices silently drops the relaunched
    instance. ``open -na`` gets us a fresh PSN."""
    import pytest

    bundle = str(tmp_path / "Murmuro.app")
    # In production sys.exit raises SystemExit and the function never
    # reaches os.execv. Mirror that by giving the patched exit the same
    # raising behaviour, otherwise control falls through and os.execv
    # runs anyway.
    with (
        patch("murmuro.restart._find_app_bundle_root", return_value=bundle),
        patch("murmuro.restart.subprocess.Popen") as popen_mock,
        patch("murmuro.restart.sys.exit", side_effect=SystemExit) as exit_mock,
        patch("murmuro.restart.os.execv") as execv_mock,
        patch("murmuro.restart.QApplication.instance", return_value=None),
        pytest.raises(SystemExit),
    ):
        _default_relaunch()

    popen_mock.assert_called_once_with(["open", "-na", bundle])
    exit_mock.assert_called_once_with(0)
    execv_mock.assert_not_called()


def test_default_relaunch_falls_back_to_execv_outside_a_bundle():
    """Dev mode (`python -m murmuro`) has no .app ancestor — replace the
    process image directly."""
    with (
        patch("murmuro.restart._find_app_bundle_root", return_value=None),
        patch("murmuro.restart.os.execv") as execv_mock,
        patch("murmuro.restart.subprocess.Popen") as popen_mock,
        patch("murmuro.restart.QApplication.instance", return_value=None),
    ):
        _default_relaunch()

    execv_mock.assert_called_once_with(
        sys.executable, [sys.executable, *sys.argv]
    )
    popen_mock.assert_not_called()


def test_default_relaunch_quits_qapplication_first_when_present():
    """When a QApplication is alive we ask it to quit before relaunching —
    lets Qt run any cleanup it needs."""
    fake_app = type("FakeApp", (), {"quit_called": False})
    fake_app.quit = lambda self=fake_app: setattr(fake_app, "quit_called", True)

    with (
        patch("murmuro.restart._find_app_bundle_root", return_value=None),
        patch("murmuro.restart.os.execv"),
        patch("murmuro.restart.QApplication.instance", return_value=fake_app),
    ):
        _default_relaunch()

    assert fake_app.quit_called is True
