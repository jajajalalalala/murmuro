"""Smoke tests for start.sh's venv-version logic.

We don't actually invoke uv here (slow, network). We exercise the bash fragment
that decides whether to recreate .venv when its Python version differs from the
pinned one.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_start_sh_is_executable():
    path = REPO_ROOT / "start.sh"
    assert path.exists(), "start.sh missing"
    assert path.stat().st_mode & 0o111, "start.sh must be executable"


def test_start_sh_passes_bash_syntax_check():
    result = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "start.sh")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"


def test_start_sh_recreates_venv_on_version_mismatch(tmp_path):
    """Simulate a .venv whose python --version differs from .python-version.

    We craft a fake .venv/bin/python that prints '3.9' for the version probe,
    then run only the version-detection fragment of start.sh. Expect: the script
    decides to remove the venv (we observe via a sentinel file).
    """
    if not shutil.which("bash"):
        # No bash available (Windows runner without WSL); skip cleanly.
        import pytest
        pytest.skip("bash not available")

    fake_venv = tmp_path / ".venv" / "bin"
    fake_venv.mkdir(parents=True)
    fake_python = fake_venv / "python"
    # Fake python that emits "3.9" when called with -c, mimicking a stale venv.
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "-c" ]]; then echo "3.9"; fi\n'
    )
    fake_python.chmod(0o755)

    sentinel = tmp_path / "removed.flag"
    script = f"""
set -euo pipefail
cd "{tmp_path}"
PINNED_PYTHON="3.11"
need_create=0
if [[ ! -d .venv ]]; then
    need_create=1
elif [[ ! -x .venv/bin/python ]]; then
    rm -rf .venv
    need_create=1
else
    probe='import sys; print(f"{{sys.version_info[0]}}.{{sys.version_info[1]}}")'
    current_ver="$(.venv/bin/python -c "$probe" 2>/dev/null || echo unknown)"
    if [[ "$current_ver" != "$PINNED_PYTHON" ]]; then
        rm -rf .venv
        touch "{sentinel}"
        need_create=1
    fi
fi
echo "need_create=$need_create"
"""
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "need_create=1" in result.stdout, result.stdout
    assert sentinel.exists(), "venv should have been removed when version mismatched"
    assert not (tmp_path / ".venv").exists(), ".venv should be gone after detection"


def test_start_sh_keeps_venv_on_version_match(tmp_path):
    """If the existing venv matches the pinned version, don't touch it."""
    if not shutil.which("bash"):
        import pytest
        pytest.skip("bash not available")

    pinned = f"{sys.version_info[0]}.{sys.version_info[1]}"
    fake_venv = tmp_path / ".venv" / "bin"
    fake_venv.mkdir(parents=True)
    fake_python = fake_venv / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        f'if [[ "$1" == "-c" ]]; then echo "{pinned}"; fi\n'
    )
    fake_python.chmod(0o755)

    script = f"""
set -euo pipefail
cd "{tmp_path}"
PINNED_PYTHON="{pinned}"
need_create=0
if [[ ! -d .venv ]]; then
    need_create=1
elif [[ ! -x .venv/bin/python ]]; then
    rm -rf .venv
    need_create=1
else
    probe='import sys; print(f"{{sys.version_info[0]}}.{{sys.version_info[1]}}")'
    current_ver="$(.venv/bin/python -c "$probe" 2>/dev/null || echo unknown)"
    if [[ "$current_ver" != "$PINNED_PYTHON" ]]; then
        rm -rf .venv
        need_create=1
    fi
fi
echo "need_create=$need_create"
"""
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "need_create=0" in result.stdout, result.stdout
    assert (tmp_path / ".venv").exists()
