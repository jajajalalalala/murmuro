"""Wipe Murmuro's on-disk state.

Driven by ``murmuro --uninstall``. Removes:

* the user config dir (``config.toml`` lives here)
* the log dir (``murmuro.log`` and rotated copies)
* Murmuro's private model store under
  ``platformdirs.user_data_dir("Murmuro") / "models"`` (introduced in
  v0.6 — see issue #12). Pre-v0.6 downloads in
  ``~/.cache/huggingface/hub/`` are *not* touched: Murmuro no longer
  manages that directory and we don't know which entries belong to
  Murmuro vs. another HuggingFace-using app on the user's machine.
  The user is shown an "rm -rf" hint so they can clean up manually
  if they want to.

Things this **doesn't** touch — those are user-managed and removing
them automatically would violate the principle of least surprise:

* the ``Murmuro.app`` bundle, if installed (``rm -rf /Applications/Murmuro.app``)
* the source checkout / virtualenv if running via ``start.sh``
* macOS Privacy & Security entries (Input Monitoring / Accessibility) —
  the OS only lets the user revoke those manually
* the legacy HuggingFace cache (see above)

The uninstall flow lists what it found, asks for confirmation
(unless ``--yes`` was passed), then removes each target. Failures are
reported but don't stop the rest of the cleanup — a partial uninstall
is better than aborting halfway.
"""
from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import _logging as log_mod
from . import config as config_mod
from .transcribe.factory import default_local_download_root


@dataclass(frozen=True)
class Target:
    label: str
    path: Path

    def exists(self) -> bool:
        return self.path.exists()


def _model_store_root() -> Path:
    """Murmuro's private model store path (the new v0.6+ default).

    Kept as a thin wrapper so tests can monkey-patch a single name.
    """
    return default_local_download_root()


def collect_targets() -> list[Target]:
    """Build the list of paths an uninstall would remove. Pure — no I/O
    other than the existence checks the caller might run."""
    targets: list[Target] = [
        Target("Config", config_mod.config_path().parent),
        Target("Logs", log_mod.log_path().parent),
    ]
    store = _model_store_root()
    if store.is_dir():
        targets.append(Target("Model store", store))
    return targets


def _default_confirm(prompt: str) -> bool:
    """Interactive y/n prompt; defaults to no on Enter."""
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def run(
    *,
    assume_yes: bool = False,
    dry_run: bool = False,
    out=sys.stdout,
    confirm: Callable[[str], bool] = _default_confirm,
) -> int:
    """Print plan, optionally confirm, remove. Returns process exit code.

    Tests call this directly with monkey-patched path helpers so no real
    files are touched.
    """
    targets = collect_targets()
    present = [t for t in targets if t.exists()]
    print("Murmuro uninstall — the following will be removed:", file=out)
    if not present:
        print("  (nothing — no Murmuro state found on disk)", file=out)
        return 0
    for t in present:
        print(f"  • {t.label}: {t.path}", file=out)

    print(file=out)
    print(
        "Manual cleanup (this command can't do these for you):", file=out,
    )
    print(
        "  • /Applications/Murmuro.app — drag to Trash if installed",
        file=out,
    )
    print(
        "  • System Settings → Privacy & Security → Input Monitoring "
        "/ Accessibility — revoke the entry for Murmuro.app or your "
        "Python binary",
        file=out,
    )
    # Models downloaded before v0.6 lived in the shared HuggingFace
    # cache. Murmuro stopped managing that path in #12, so we leave it
    # alone here and surface a copy-pasteable hint instead. Shown for
    # both --dry-run and the real uninstall flow.
    print(
        "  • Pre-v0.6 model downloads may still be in "
        "~/.cache/huggingface/hub/ — Murmuro no longer manages that "
        "directory. Remove manually if desired:",
        file=out,
    )
    print(
        "      rm -rf ~/.cache/huggingface/hub/"
        "models--Systran--faster-whisper-*",
        file=out,
    )

    if dry_run:
        print("\n--dry-run: nothing removed.", file=out)
        return 0

    if not assume_yes:
        print(file=out)
        if not confirm("Proceed with uninstall? [y/N] "):
            print("Aborted.", file=out)
            return 1

    failures: list[tuple[Target, OSError]] = []
    for t in present:
        try:
            shutil.rmtree(t.path)
            print(f"  removed {t.path}", file=out)
        except OSError as exc:
            failures.append((t, exc))
            print(f"  FAILED to remove {t.path}: {exc}", file=out)

    if failures:
        print(
            f"\nUninstall finished with {len(failures)} error(s). "
            "Some files may need to be removed manually.",
            file=out,
        )
        return 2
    print("\nUninstall complete.", file=out)
    return 0


__all__ = ["Target", "collect_targets", "run"]
