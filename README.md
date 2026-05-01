# Murmuro

> Press a key. Speak. Get text.

Free, local-first dictation for macOS. Hold a hotkey, speak, release — your words appear at the cursor in any app. No subscription, no cloud round-trip, no telemetry.

🌐 **[murmuro splash & download →](https://jajajalalalala.github.io/murmuro/)**

## Status

**v1.0** — packaged `.app`, push-to-talk, auto-paste, themed UI, local + cloud providers, click-to-record hotkeys (incl. `Fn`), live model download progress, start/stop beeps, silent mode, full uninstall command, GitHub Pages splash, automated release pipeline. See [ROADMAP.md](ROADMAP.md) for the full log and v1.1+ backlog.

## Features

- 🎙️  **Push-to-talk hotkey** — hold any key (default `right ⌥` on macOS, `right Alt` on Windows). Click-to-record a new shortcut from any key on the keyboard, including `Fn`.
- 🧠 **Local Whisper** via [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) — pick `tiny` → `large-v3` and `distil-large-v3`. One-click download with progress bar; per-row delete to free disk.
- 🔌 **Optional cloud** — OpenAI / Groq / Kimi / DeepSeek / any OpenAI-compatible endpoint. Pluggable provider registry, no lock-in.
- 📋 **Auto-paste at cursor** — works in browsers, IDEs, terminals, Slack, Notion, Mail. Falls back to clipboard if the focused app blocks paste.
- 🪶 **Menu-bar only** — no Dock icon, no focus stealing. Recording HUD anchors at bottom-center, out of the menu bar / notch.
- 🔔 **Start/stop beeps** — eyes-free confirmation. Toggle Silent mode from the tray menu or Home.
- 🧹 **Clean uninstall** — `murmuro --uninstall` wipes config, logs, and downloaded Whisper models. `--dry-run` previews; other HuggingFace caches are left alone.

## Non-goals

Murmuro is a **dictation** tool, not an AI assistant.

- ❌ AI rewriting / grammar fixing
- ❌ Cloud sync, accounts, teams
- ❌ Real-time streaming transcription
- ❌ Mobile platforms

## Install

### macOS — recommended

1. **Download** `Murmuro.dmg` — [direct download](https://github.com/jajajalalalala/murmuro/releases/latest/download/Murmuro.dmg) or [release page](https://github.com/jajajalalalala/murmuro/releases/latest).
2. **Drag** `Murmuro.app` from the mounted `.dmg` into `/Applications`.
3. **Clear the macOS quarantine flag** so Gatekeeper lets the app launch:

   ```bash
   xattr -dr com.apple.quarantine /Applications/Murmuro.app
   ```

   Without this, macOS refuses to open the app with the warning *"Apple cannot check it for malicious software."* This is one-time per install. (Why this is needed → see [Why the bypass?](#why-the-quarantine-bypass) below.)
4. **Launch** Murmuro. macOS will prompt for **Microphone** and **Input Monitoring** permissions — grant both, then click **Quit & Reopen** when prompted.

To launch on boot, add Murmuro to **System Settings → General → Login Items**.

#### Why the quarantine bypass?

macOS Gatekeeper refuses to launch downloaded apps unless they are **notarized** through Apple — a service that requires a paid [Apple Developer Program](https://developer.apple.com/programs/) membership ($99/yr). Murmuro v1.0 ships **ad-hoc signed** (free, but not notarized), so every download arrives with a `com.apple.quarantine` flag that blocks launch.

The `xattr -dr com.apple.quarantine …` command strips that flag and tells macOS *"I trust this download."* It does **not** disable Gatekeeper system-wide and does **not** weaken your security for other apps.

If you'd prefer a workflow that avoids this step entirely:

- **Build from source** ([instructions below](#from-source)) — local builds aren't quarantined.
- **Verify the SHA256** of the downloaded `.dmg` against the value on the [release page](https://github.com/jajajalalalala/murmuro/releases/latest) before running `xattr` if you want a manual integrity check.

Real Apple-notarized signing is on the [v1.1+ roadmap](ROADMAP.md). Once it lands, end users won't need this step.

### From source

The bundled `start.sh` installs [uv](https://github.com/astral-sh/uv) (if missing), pins Python via `.python-version`, creates an isolated venv, installs deps, and launches the menu-bar app. **No system Python required.**

```bash
git clone https://github.com/jajajalalalala/murmuro.git
cd murmuro
./start.sh              # default: launches the menu-bar tray app
./start.sh --cli        # CLI mode (Enter to start/stop)
./start.sh --setup-only # install dependencies, don't launch
./start.sh --reset      # wipe .venv and reinstall
```

To build a standalone `.app` from source:

```bash
./build.sh              # produces dist/Murmuro.app
./build.sh --clean      # wipe dist/ and build/ first
```

The build bundles Python + all deps, embeds the icon, sets `LSUIElement=true` (menu-bar only), patches Info.plist with permission strings, and ad-hoc-codesigns the bundle.

### Windows

Run from source via `./start.sh` (WSL or Git Bash). Native `Murmuro.exe` packaging is on the v1.1+ backlog — no Windows daily-driver yet.

## Usage

1. **Hold the hotkey** (default `right ⌥`).
2. **Speak.**
3. **Release.** Text appears at your cursor.

The first run downloads a Whisper model (~150 MB for `base`).

### Change the hotkey

Tray icon → **Open Murmuro…** → **Shortcuts** → click **Record** → press the key (or combo) you want. Modifier-only hotkeys commit on release; combos with a non-modifier (e.g. `⌃⇧Space`) commit on the non-modifier press. `Esc` cancels.

Power users can hand-edit the `hotkey` field in the config file (path printed by `murmuro --show-config`) using [pynput hotkey syntax](https://pynput.readthedocs.io/en/latest/keyboard.html#monitoring-the-keyboard) — e.g. `<f9>`, `<ctrl>+<shift>+<space>`.

### Pick a model

Tray icon → **Open Murmuro…** → **Models**:

- **Local (on-device)** — list of faster-whisper models with size + a Download or Use button. The first transcription after picking a fresh model has a small load-into-memory delay; subsequent ones are instant.
- **Cloud** — enter the env var name that holds your API key (default `OPENAI_API_KEY`). The status line under the field tells you whether the var is set in the current session.

The Models page is wired through a small provider registry — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for adding a new one.

### Uninstall

```bash
murmuro --uninstall --dry-run   # preview what would be removed
murmuro --uninstall --yes       # actually remove (config, logs, Whisper caches)
```

The bundled `Murmuro.app` and the macOS Privacy & Security entries are listed in the printed plan but not deleted automatically — drag the app to the Trash and revoke the toggles manually.

## macOS permissions — what's needed and why

Murmuro needs two grants:

1. **Microphone** — recording audio.
2. **Input Monitoring** — observing the global hotkey. Without this you'll see `This process is not trusted!` in the log and the hotkey will silently do nothing.

> ⚠️  macOS only re-checks Input Monitoring at process start. After flipping the toggle ON, **quit and relaunch Murmuro** for it to take effect.

**Which binary needs the permission?**

- If you launched via `./start.sh`, it's `.venv/bin/python` (or your terminal app, depending on macOS version). The grant is fragile — it can break if the venv is recreated.
- If you launched the bundled `Murmuro.app`, the grant attaches to the bundle. **This is the recommended path for daily use.**

> Note on rebuilds: each ad-hoc-signed `./build.sh` produces a new code identity, so macOS treats it as a new app and asks for permission again. `build.sh` runs `tccutil reset` automatically to keep stale entries from piling up. Real Developer-ID notarization (which would make grants persist across rebuilds) is on the v1.1+ backlog — for the released `.app` from GitHub, this only matters when you upgrade to a newer release.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module layout and data flow.

## License

[MIT](LICENSE)
