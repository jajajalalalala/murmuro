# Murmur Roadmap

The vision: **press a key, speak, get text** — nothing more, nothing less. Each milestone below is a *shippable* slice. Don't move forward until the previous one is real and used daily.

---

## v0.1 — "It transcribes" (CLI) ✅

**Goal:** Prove the speech-to-text loop end-to-end on the developer's machine.

- [x] Project scaffolding, README, roadmap, architecture
- [x] `audio.py` — record from default mic to in-memory PCM (16 kHz mono)
- [x] `transcribe/base.py` — `Transcriber` interface
- [x] `transcribe/local.py` — `faster-whisper` backend, lazy model load
- [x] `transcribe/openai_api.py` — OpenAI `audio.transcriptions` backend
- [x] `config.py` — load/save TOML config in user config dir
- [x] `__main__.py` — interactive CLI: Enter to start/stop, prints text + copies to clipboard

**Done when:** `murmur --cli` records my voice and outputs accurate text in <5 s for a 10 s clip.

---

## v0.2 — "Hotkey + tray" ✅

**Goal:** Stop using the terminal. Murmur lives in the menu bar.

- [x] `hotkey.py` — global push-to-talk via `pynput` (hold to record, release to stop)
- [x] `tray.py` — `QSystemTrayIcon` with colored-dot state indicator + Quit menu
- [x] `app.py` — state machine (IDLE → RECORDING → TRANSCRIBING → IDLE) wiring hotkey/recorder/transcriber
- [x] `__main__.py` — GUI by default, `--cli` for terminal mode
- [x] `start.sh` — uv-based isolated setup, one command to install + launch
- [x] `.python-version` — pin runtime so the app doesn't depend on system Python

**Done when:** I can hold the hotkey from any app, speak, and the result lands in my clipboard with a tray notification.

---

## v0.3 — "Paste at cursor"

**Goal:** No more `⌘V`. Text appears where I'm typing.

- [ ] `inject.py` — copy → simulate `⌘V` / `Ctrl+V` via `pynput`
- [ ] Preserve clipboard: save before, restore after
- [x] Recording HUD: tiny floating window with timer (waveform later)
- [ ] Cancel-by-Esc while recording

**Done when:** I can replace my typing with dictation in any app (browser, IDE, Slack) without manual paste.

---

## v1.0 — "Shippable"

**Goal:** A version a friend could install and use.

- [x] Settings window (Qt): hotkey, model size, language, backend, API key
- [ ] First-run onboarding: permissions, mic check, model download progress
- [ ] Logging + crash report to local file
- [x] Packaging: `pyinstaller` → `Murmur.app` (mac) — see `build.sh`
- [ ] Packaging: `pyinstaller` → `Murmur.exe` (Windows)
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
