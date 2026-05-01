"""Rotating-file logger so `.app` launches leave a debuggable trail.

When Murmuro is launched from Finder / `open Murmuro.app`, stdout and stderr go
nowhere the user can see, so silent failures (pynput listener not getting
events, transcriber crash on a worker thread, etc.) look identical to "the
hotkey just doesn't fire". Routing everything through `logging.getLogger
("murmuro.*")` and tee-ing it to a file fixes that.

The file lives where macOS users expect app logs:

    ~/Library/Logs/Murmuro/murmuro.log

The user can `tail -f` it to see what's happening live.
"""
from __future__ import annotations

import logging
import logging.handlers
import platform
import sys
from pathlib import Path

_CONFIGURED = False


def log_path() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Logs" / "Murmuro" / "murmuro.log"
    return Path.home() / ".local" / "state" / "murmuro" / "murmuro.log"


def setup_logging(*, debug: bool = False, also_stderr: bool = True) -> Path:
    """Idempotent. Configure the `murmuro` logger tree and return the log path."""
    global _CONFIGURED
    path = log_path()
    if _CONFIGURED:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("murmuro")
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    # Drop any pre-existing handlers (e.g. from a prior call in tests).
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.handlers.RotatingFileHandler(
        path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if also_stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    root.propagate = False
    _CONFIGURED = True
    return path


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"murmuro.{name}")
