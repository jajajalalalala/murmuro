# Murmur Roadmap

The vision: **press a key, speak, get text** — nothing more, nothing less. Each milestone below is a *shippable* slice. Don't move forward until the previous one is real and used daily.

---

## v0.1 — "It transcribes" (CLI)

**Goal:** Prove the speech-to-text loop end-to-end on the developer's machine.

- [x] Project scaffolding, README, roadmap, architecture
- [ ] `audio.py` — record from default mic to in-memory WAV (16 kHz mono)
- [ ] `transcribe/base.py` — `Transcriber` interface
- [ ] `transcribe/local.py` — `faster-whisper` backend, lazy model load
- [ ] `transcribe/openai_api.py` — OpenAI `audio.transcriptions` backend
- [ ] `config.py` — load/save TOML config in user config dir
- [ ] `__main__.py` — interactive CLI: Enter to start/stop, prints text + copies to clipboard

**Done when:** `murmur` from the terminal records my voice and outputs accurate text in <5 s for a 10 s clip.

---

## v0.2 — "Hotkey + tray"

**Goal:** Stop using the terminal. Murmur lives in the menu bar.

- [ ] `hotkey.py` — global push-to-talk via `pynput` (hold to record, release to stop)
- [ ] `tray.py` — `pystray` / Qt system tray icon with state (idle / recording / transcribing)
- [ ] App lifecycle: start on launch, runs in background
- [ ] Visual/audible cue when recording starts and stops

**Done when:** I can dictate into any text field by holding the hotkey, and result lands in clipboard.

---

## v0.3 — "Paste at cursor"

**Goal:** No more `⌘V`. Text appears where I'm typing.

- [ ] `inject.py` — copy → simulate `⌘V` / `Ctrl+V` via `pynput`
- [ ] Preserve clipboard: save before, restore after
- [ ] Recording HUD: tiny floating window with waveform/level meter
- [ ] Cancel-by-Esc while recording

**Done when:** I can replace my typing with dictation in any app (browser, IDE, Slack) without manual paste.

---

## v1.0 — "Shippable"

**Goal:** A version a friend could install and use.

- [ ] Settings window (Qt): hotkey, model size, language, backend, API key
- [ ] First-run onboarding: permissions, mic check, model download progress
- [ ] Logging + crash report to local file
- [ ] Packaging: `pyinstaller` → `Murmur.app` (mac) and `Murmur.exe` (Windows)
- [ ] Code-signing notes (mac notarization optional for personal use)
- [ ] GitHub Actions: build + release artifacts on tag
- [ ] Polished README with screenshots

**Done when:** A non-Python user can download a release, double-click, and dictate within 2 minutes.

---

## v1.1+ — Backlog (only if missed)

Each item must justify itself by being missed in daily use. Don't pre-build.

- Local model warm-up at app start (latency)
- Custom vocabulary / replacements (e.g. "claude" → "Claude")
- Transcript history viewer
- AI rewrite pass (opt-in, using OpenAI/Anthropic) — Wispr's killer feature
- Multi-language auto-detect
- Streaming transcription
- Dictionary of acronyms loaded from a text file
- Hotkey chord support (`fn fn` double-tap toggle vs hold)

---

## Principles

1. **Local-first.** No network call required for the core loop.
2. **One job.** Transcription. Not rewriting, not summarizing, not chatting.
3. **Own the binary.** No subscription, no telemetry, no auth.
4. **No premature features.** A backlog item earns its way in by being missed three times.
