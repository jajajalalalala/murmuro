"""v0.1 CLI: press Enter to start recording, Enter again to stop, get text."""
from __future__ import annotations

import argparse
import sys
import time

import pyperclip

from . import __version__, config as config_mod
from .audio import Recorder, SAMPLE_RATE
from .transcribe import build as build_transcriber


def _interactive_loop(cfg: config_mod.Config) -> None:
    transcriber = build_transcriber(cfg)
    recorder = Recorder()
    print(f"Murmur v{__version__} — backend: {cfg.backend}, language: {cfg.language}")
    print("Press Enter to start recording, Enter again to stop. Ctrl-C to quit.\n")
    while True:
        try:
            input("▶  ready — Enter to record... ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
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
        try:
            pyperclip.copy(text)
            paste_note = "  [copied to clipboard]"
        except pyperclip.PyperclipException:
            paste_note = "  [clipboard unavailable]"
        print(f"✓  ({dt:.1f}s){paste_note}\n   {text}\n")


def main() -> int:
    parser = argparse.ArgumentParser(prog="murmur", description="Press a key, speak, get text.")
    parser.add_argument("--version", action="version", version=f"murmur {__version__}")
    parser.add_argument(
        "--backend",
        choices=["local", "openai"],
        help="Override config backend for this run.",
    )
    parser.add_argument("--language", help="Override language (ISO 639-1, or 'auto').")
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print config path and contents, then exit.",
    )
    args = parser.parse_args()

    cfg = config_mod.load()
    if args.backend:
        cfg.backend = args.backend
    if args.language:
        cfg.language = args.language

    if args.show_config:
        print(f"config: {config_mod.config_path()}")
        print(f"backend={cfg.backend} language={cfg.language} hotkey={cfg.hotkey}")
        return 0

    try:
        _interactive_loop(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
