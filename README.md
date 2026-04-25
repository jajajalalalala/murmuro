# Murmur

> Press a key. Speak. Get text. — A minimal, local-first dictation tool inspired by [Wispr Flow](https://wisprflow.ai/).

Murmur is a personal voice-to-text dictation tool for macOS and Windows. Hold a hotkey, speak, release — your words appear at the cursor. Runs **locally by default** via [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper), with an optional OpenAI Whisper API backend.

## Why another one?

[Wispr Flow](https://wisprflow.ai/) is excellent but closed-source, subscription-based, and full of features I don't need. Murmur is what I want: a single hotkey, a single job, a single binary I own.

## Status

🚧 **v0.1** — early development. See [ROADMAP.md](ROADMAP.md).

## Features (v1.0 target)

- 🎙️  Push-to-talk global hotkey (default `fn` on macOS, `right alt` on Windows)
- 🧠 Local Whisper transcription (no internet required)
- 🔌 Pluggable backend: switch to OpenAI API with one click
- 📋 Auto-paste at cursor, fallback to clipboard
- 🪶 Menu bar / system tray app — no Dock icon
- ⚙️  Settings UI for hotkey, model size, language, backend

## Non-goals

- AI rewriting / grammar fixing (use a separate tool)
- Cloud sync, accounts, teams
- Real-time streaming transcription
- Mobile platforms

## Quick start (v0.1 CLI)

```bash
git clone https://github.com/<you>/murmur.git
cd murmur
python -m venv .venv && source .venv/bin/activate
pip install -e .
murmur                  # interactive: press Enter to start/stop recording
```

The first run downloads a Whisper model (~150 MB for `base`).

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module layout and data flow.

## Roadmap

See [ROADMAP.md](ROADMAP.md). TL;DR:

- **v0.1** ✅ CLI: record → transcribe → clipboard
- **v0.2** Global hotkey + tray icon
- **v0.3** Auto-paste at cursor + recording HUD
- **v1.0** Settings UI + packaged `.app` / `.exe` + GitHub release
- **v1.1+** Custom vocabulary, history, AI rewrite (opt-in)

## License

MIT
