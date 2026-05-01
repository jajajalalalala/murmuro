"""Smoke test for the file logger setup."""
from __future__ import annotations

import logging
from pathlib import Path

from murmuro import _logging as logging_mod


def test_setup_logging_writes_to_file(tmp_path, monkeypatch):
    target = tmp_path / "Logs" / "Murmuro" / "murmuro.log"
    monkeypatch.setattr(logging_mod, "log_path", lambda: target)
    # Force a fresh setup even if a previous test configured it.
    monkeypatch.setattr(logging_mod, "_CONFIGURED", False)
    for h in list(logging.getLogger("murmuro").handlers):
        logging.getLogger("murmuro").removeHandler(h)

    path = logging_mod.setup_logging(also_stderr=False)
    assert path == target
    assert target.parent.is_dir()

    log = logging_mod.get_logger("test")
    log.info("hello-from-test")

    for h in logging.getLogger("murmuro").handlers:
        h.flush()

    assert target.exists()
    contents = Path(target).read_text(encoding="utf-8")
    assert "hello-from-test" in contents
    assert "murmuro.test" in contents
