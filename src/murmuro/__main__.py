"""Murmuro entrypoint.

Default: launches the menu-bar tray app with global push-to-talk hotkey.
With --cli: drops to interactive Enter-to-record CLI loop (useful on
machines without a graphical session, or for quick smoke tests).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from . import __version__
from . import config as config_mod
from ._logging import get_logger, setup_logging
from .audio import SAMPLE_RATE, Recorder
from .inject import to_clipboard
from .transcribe import build as build_transcriber


def _cli_loop(cfg: config_mod.Config) -> int:
    transcriber = build_transcriber(cfg)
    recorder = Recorder()
    print(f"Murmuro v{__version__} — backend: {cfg.backend}, language: {cfg.language}")
    print("CLI mode. Press Enter to start recording, Enter again to stop. Ctrl-C to quit.\n")
    while True:
        try:
            input("▶  ready — Enter to record... ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        recorder.start()
        try:
            input("●  recording — Enter to stop... ")
        except KeyboardInterrupt:
            recorder.stop()
            print("\ncancelled.")
            continue
        pcm = recorder.stop()
        duration = pcm.size / SAMPLE_RATE
        if duration < 0.2:
            print("(too short, skipping)\n")
            continue
        print(f"⏳ transcribing {duration:.1f}s of audio...")
        t0 = time.time()
        text = transcriber.transcribe(pcm, SAMPLE_RATE, language=cfg.language)
        dt = time.time() - t0
        if not text:
            print("(no speech detected)\n")
            continue
        copied = to_clipboard(text) if cfg.auto_paste else False
        suffix = "  [copied to clipboard]" if copied else ""
        print(f"✓  ({dt:.1f}s){suffix}\n   {text}\n")


def _gui() -> int:
    try:
        from .tray import run_tray
    except ImportError as e:
        print(
            f"GUI dependencies are missing: {e}\n"
            "Install with:  pip install -e '.[gui]'   "
            "or run with --cli for the terminal mode.",
            file=sys.stderr,
        )
        return 2
    return run_tray(config_mod.load())


def main() -> int:
    parser = argparse.ArgumentParser(prog="murmuro", description="Press a key, speak, get text.")
    parser.add_argument("--version", action="version", version=f"murmuro {__version__}")
    parser.add_argument("--cli", action="store_true", help="Run in terminal CLI mode (no tray).")
    parser.add_argument(
        "--backend",
        choices=["local", "cloud", "openai"],
        help="Override config backend. ``openai`` is accepted as a legacy alias for "
             "``cloud`` (with cloud_provider_id=openai).",
    )
    parser.add_argument("--language", help="Override language (ISO 639-1, or 'auto').")
    parser.add_argument("--show-config", action="store_true", help="Print config path and exit.")
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove config, logs, and downloaded local models, then exit.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts (currently used by --uninstall).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --uninstall: print what would be removed without removing it.",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Verbose logging (also via MURMURO_DEBUG=1)."
    )
    args = parser.parse_args()

    # Uninstall must run before setup_logging — otherwise it'd recreate
    # the log dir we're trying to delete.
    if args.uninstall:
        from .uninstall import run as run_uninstall
        return run_uninstall(assume_yes=args.yes, dry_run=args.dry_run)

    debug = args.debug or os.environ.get("MURMURO_DEBUG") == "1"
    log_file = setup_logging(debug=debug)
    log = get_logger("main")
    log.info("Murmuro v%s starting (pid=%d, debug=%s)", __version__, os.getpid(), debug)
    log.info("Log file: %s", log_file)

    cfg = config_mod.load()
    if args.backend:
        # Legacy ``--backend openai`` keeps working: collapse it to the
        # post-#17 (backend=cloud, cloud_provider_id=openai) shape so the
        # factory has a single dispatch path.
        if args.backend == "openai":
            cfg.backend = "cloud"
            cfg.cloud_provider_id = "openai"
        else:
            cfg.backend = args.backend
    if args.language:
        cfg.language = args.language

    if args.show_config:
        print(f"config: {config_mod.config_path()}")
        print(f"backend={cfg.backend} language={cfg.language} hotkey={cfg.hotkey}")
        return 0

    if args.cli:
        return _cli_loop(cfg)
    _warn_if_input_monitoring_denied()
    return _gui()


def _warn_if_input_monitoring_denied() -> None:
    """Warn loudly on macOS before the GUI starts, so the user sees it in stderr."""
    from .permissions import (
        AccessibilityStatus,
        InputMonitoringStatus,
        accessibility_status,
        input_monitoring_status,
    )

    log = get_logger("main")
    status = input_monitoring_status()
    log.info("Input Monitoring status: %s", status.value)
    ax = accessibility_status()
    log.info("Accessibility status: %s (needed for auto-paste)", ax.value)
    if status == InputMonitoringStatus.DENIED:
        print(
            "\n[murmuro] macOS Input Monitoring is DENIED for this binary.\n"
            "         The hotkey will not work until you enable it in:\n"
            "         System Settings → Privacy & Security → Input Monitoring\n",
            file=sys.stderr,
        )
    if ax == AccessibilityStatus.DENIED:
        print(
            "\n[murmuro] macOS Accessibility is not granted for this binary.\n"
            "         Auto-paste at cursor (⌘V) will fall back to clipboard-only.\n"
            "         Enable in: System Settings → Privacy & Security → Accessibility\n",
            file=sys.stderr,
        )


if __name__ == "__main__":
    raise SystemExit(main())
