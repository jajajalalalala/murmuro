# Murmur

> Press a key. Speak. Get text. — A minimal, local-first dictation tool inspired by [Wispr Flow](https://wisprflow.ai/).

Murmur is a personal voice-to-text dictation tool for macOS and Windows. Hold a hotkey, speak, release — your words appear at the cursor. Runs **locally by default** via [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper), with an optional OpenAI Whisper API backend.

## Why another one?

[Wispr Flow](https://wisprflow.ai/) is excellent but closed-source, subscription-based, and full of features I don't need. Murmur is what I want: a single hotkey, a single job, a single binary I own.

## Status

🚧 **v0.4-dev** — push-to-talk, packaged macOS `.app`, reliable auto-paste, main window with Home / Shortcuts / Models pages. See [ROADMAP.md](ROADMAP.md).

## Features

- 🎙️  Push-to-talk global hotkey, configured by **clicking Record and pressing the key** (default `Right Option` on macOS, `Right Alt` on Windows)
- 🧠 Local Whisper transcription via faster-whisper (no internet required); pick from `tiny` → `large-v3` and `distil-large-v3` with one-click downloads
- 🔌 Pluggable backend: switch to OpenAI Whisper API by entering an env-var name; the registry is structured so Groq / Kimi / DeepSeek slot in next
- 📋 Reliable auto-paste at cursor on macOS (works around CGEventPost autorepeat quirks and HUD focus stealing), with clipboard-only fallback
- 🪶 Menu bar / system tray app — no Dock icon, no focus-stealing HUD
- 🪟 Main window with three pages: **Home** (state + last 5 transcripts + global toggles), **Shortcuts**, **Models**

## Non-goals

- AI rewriting / grammar fixing (use a separate tool)
- Cloud sync, accounts, teams
- Real-time streaming transcription
- Mobile platforms

## Quick start

The bundled `start.sh` installs [uv](https://github.com/astral-sh/uv) (if missing), pins Python via `.python-version`, creates an isolated venv, installs deps, and launches Murmur. **You do not need a system Python — uv installs it.**

```bash
git clone https://github.com/jajajalalalala/murmur.git
cd murmur
./start.sh              # default: launches the menu-bar tray app
./start.sh --cli        # CLI mode (Enter to start/stop)
./start.sh --setup-only # install dependencies, don't launch
./start.sh --reset      # wipe .venv and reinstall
```

The first run downloads a Whisper model (~150 MB for `base`).

### Default hotkey
- macOS: `right Option (⌥)` — hold to record, release to transcribe
- Windows: `right Alt`

Change it from the menu bar: click the Murmur tray icon → **Open Murmur…** → **Shortcuts** → click **Record** → press the key (or combo) you want. Modifier-only hotkeys commit on release; combos with a non-modifier (e.g. `⌃⇧Space`) commit on the non-modifier press. Esc cancels.

Power users can still hand-edit the `hotkey` field in the config file (printed by `murmur --show-config`) using [pynput hotkey syntax](https://pynput.readthedocs.io/en/latest/keyboard.html#monitoring-the-keyboard) — e.g. `<f9>`, `<ctrl>+<shift>+<space>`.

### Picking a model

Open the main window → **Models** page:

- **Local (on-device)** — list of faster-whisper models with size + a Download or Use button. Click Download to fetch the model into the HuggingFace cache; flip to it with **Use**. The first transcription after picking a fresh model has a small load-into-memory delay; subsequent ones are instant.
- **OpenAI Whisper** — enter the env var name that holds your API key (default `OPENAI_API_KEY`). The page tells you whether the var is currently set in your shell. The status line under the field tells you whether the var is currently set in this session.

The Models page is wired through a small provider registry, so the next provider (Groq, Kimi, DeepSeek, custom OpenAI-compatible endpoint) is a one-file extension — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### macOS permissions

Murmur needs **two** permissions on macOS — both granted to whichever binary is running:

1. **Microphone** — recording audio.
2. **Input Monitoring** — observing the global hotkey. Without this you'll see
   `This process is not trusted!` and the hotkey will silently do nothing.

On first launch Murmur asks macOS to show the prompt. If you previously denied
or never saw it, Murmur opens a dialog with an "Open System Settings" button
that drops you into **System Settings → Privacy & Security → Input Monitoring**.

> ⚠️  macOS only re-checks Input Monitoring at process start. After flipping
> the toggle ON, **quit and relaunch Murmur** for it to take effect.

**Which binary needs the permission?**
- If you launched via `./start.sh`, it's `.venv/bin/python` (or your terminal app, depending on macOS version). The grant is fragile — it can break if the venv is recreated.
- If you launched `dist/Murmur.app`, the grant attaches to the bundle and survives rebuilds. **This is the recommended path for daily use.**

## Run as a real macOS app (no terminal)

Once you've used `start.sh` once and confirmed it works, you can build a standalone `Murmur.app`:

```bash
./build.sh                      # produces dist/Murmur.app
open dist/Murmur.app            # or drag into /Applications
```

The build:
- Bundles Python + all dependencies, so the app runs without any system Python
- Generates and embeds the Murmur icon (teal/violet microphone)
- Sets `LSUIElement=true` so Murmur lives only in the menu bar — no Dock icon
- Adds the macOS permission strings so the prompts are human-readable
- Ad-hoc-codesigns the bundle so Gatekeeper allows it on your machine

Drag `Murmur.app` into `/Applications` and add it to System Settings → General → **Login Items** to launch on boot.

> **Windows:** packaging support is on the roadmap (v1.0). For now, run via `./start.sh` on Windows under WSL or Git Bash.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module layout and data flow.

## Roadmap

See [ROADMAP.md](ROADMAP.md). TL;DR:

- **v0.1** ✅ CLI: record → transcribe → clipboard
- **v0.2** ✅ Global hotkey + tray icon
- **v0.3** ✅ Auto-paste at cursor + recording HUD (focus-safe NSPanel)
- **v0.4** ✅ Main window UI: Home / Shortcuts / Models, click-to-record hotkey, local model downloads
- **v0.5** Provider expansion: Groq / Kimi / DeepSeek via OpenAI-compatible registry
- **v1.0** First-run onboarding + Windows packaging + GitHub release
- **v1.1+** Hands-free toggle, custom vocabulary, transcript history, AI rewrite (opt-in)

## License

MIT
