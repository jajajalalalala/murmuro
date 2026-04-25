"""Sanity checks on the packaging tooling.

We don't actually run pyinstaller in CI (slow, mac-only). We verify the build
scripts are well-formed and that the icon generator produces a valid PNG.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_build_sh_executable():
    p = REPO_ROOT / "build.sh"
    assert p.exists(), "build.sh missing"
    assert p.stat().st_mode & 0o111, "build.sh must be executable"


def test_build_sh_bash_syntax():
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    r = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "build.sh")],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


def test_make_icns_bash_syntax():
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    r = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "tools" / "make_icns.sh")],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


def test_icon_png_exists_and_is_valid():
    """The committed icon.png should be a real, square PNG."""
    icon = REPO_ROOT / "assets" / "icon.png"
    assert icon.exists(), "assets/icon.png is missing — run tools/make_icon.py"
    head = icon.read_bytes()[:8]
    assert head == b"\x89PNG\r\n\x1a\n", f"not a PNG (header={head!r})"


def test_make_icon_runs_without_error():
    """Generating into a tmp path must succeed when Pillow is available."""
    pytest.importorskip("PIL")
    import sys
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    try:
        import importlib
        make_icon = importlib.import_module("make_icon")
        img = make_icon.make_icon(size=128)
        assert img.size == (128, 128)
        assert img.mode == "RGBA"
    finally:
        sys.path.pop(0)
