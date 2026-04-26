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

## v0.3 — "Paste at cursor" ✅

**Goal:** No more `⌘V`. Text appears where I'm typing.

- [x] `inject.py` — copy → CGEventPost `⌘V` (macOS) via ctypes; `pynput` on Windows
- [x] CGEventPost reliability fixes: `kCGKeyboardEventAutorepeat=0`, flagsChanged-clear before each chord, paste routed through the host's UI thread
- [x] Recording HUD: floating pill with timer; promoted to a non-activating status-level NSPanel so it never steals focus from the active text field
- [x] Esc cancels the hotkey-recording session in Settings

**Done when:** I can replace my typing with dictation in any app (browser, IDE, Slack) without manual paste — done.

---

## v0.4 — "Main window UI" ✅

**Goal:** A real settings/home window, not a tiny modal.

- [x] `main_window.py` — `QMainWindow` with left-rail nav + `QStackedWidget`
- [x] `pages/home.py` — state pill, last 5 transcripts (click to recopy), auto-paste / show-HUD toggles, language picker
- [x] `pages/shortcuts.py` — push-to-talk row using the click-to-record widget
- [x] `pages/models.py` — provider dropdown swaps between Local model list (Download / Use buttons, faster-whisper cache check) and Cloud panel (API key env var + model)
- [x] `providers.py` — `LocalModel` and `CloudProvider` dataclasses + registry
- [x] Tray left-click opens the window; "Settings…" menu item replaced with **Open Murmur…**

**Done when:** I can configure everything from a window that looks like an app, not a dialog.

---

## v0.5 — "Daily-driver polish" ✅

**Goal:** Sand off the rough edges of v0.4 so Murmur feels like a real app. Ordered by user-felt priority — top items ship first.

### P0 — Pain points blocking daily use
- [x] **Full keyboard coverage for hotkeys** (`feat/hotkeys-full-coverage`)
  - [x] Expand `hotkey_recorder._MAC_VK_NAMES` to all standard keys: digits, letters, punctuation, arrows, navigation cluster (home/end/pgup/pgdn/del/backspace), caps_lock, full F1–F20
  - [x] First-launch-style **Test any key** probe on the Shortcuts page (`key_probe.py`) so the user can verify what's recordable on their OS / locale
  - [x] `fn` key on macOS: `NSEvent.addGlobalMonitorForEventsMatchingMask:NSEventMaskFlagsChanged` side channel, surfaced as a synthesized `<fn>` token
  - [x] Tests for each new VK in the recorder map
  - [ ] Same coverage on Windows (Qt nativeVirtualKey → pynput name) — deferred, no Windows daily-driver
- [x] **UI redesign — colorful, accessible** (`feat/ui-redesign`)
  - [x] Custom QPalette + single stylesheet shipped from `ui/theme.py`: violet accent (`#7c5cff`), distinct surface colors for left rail vs content, auto light/dark detection (`MURMUR_FORCE_THEME` override for tests)
  - [x] Style: card-grouped sections, accent state pill, primary action buttons, focus-ring on inputs
  - [x] Verified contrast in macOS Light **and** Dark; section labels and dim text deliberately pushed away from window background
  - [x] About page added under nav so version / log path / config path are one click away

### P1 — Quality-of-life
- [x] **Wrapped, timestamped transcript list** — Home transcript rows show `HH:MM` + the text on its own line, word-wrap fills the card width, raw text retained at `UserRole` for click-to-copy. (Full table view deferred to v1.1+ — wrapping was the actual pain point.)
- [x] **Model download progress** (`feat/model-download-progress`) — `_dir_size_bytes` walks the HF cache dir and a 500 ms `QTimer` feeds a `QProgressBar` per `_LocalModelRow`; clamps to 99% so the worker's `finished` signal owns completion.

### P2 — Provider expansion (was v0.5)
- [ ] `transcribe/openai_compatible.py` — single transcriber covering OpenAI / Groq / DeepSeek / Kimi / custom
- [ ] Add Groq, Kimi, DeepSeek rows to `CLOUD_PROVIDERS`
- [ ] Per-provider rate hint shown on the Models page
- [ ] "Test connection" button that pings the chosen endpoint with a 1-second silence clip

**Done when:** Every key on my keyboard is selectable as a hotkey, the window is readable in dark mode without squinting, transcripts show with timestamps, model downloads show a progress bar, and Groq free-tier works end-to-end.

---

## v1.0 — "Shippable"

**Goal:** A version a friend could install and use.

- [ ] First-run onboarding: permissions, mic check, model download progress
- [x] Logging to local file (`~/Library/Logs/Murmur/murmur.log` on macOS)
- [x] Packaging: `pyinstaller` → `Murmur.app` (mac) — see `build.sh`
- [ ] Packaging: `pyinstaller` → `Murmur.exe` (Windows)
- [ ] Code-signing notes (mac notarization optional for personal use)
- [ ] GitHub Actions: build + release artifacts on tag
- [ ] Polished README with screenshots

**Done when:** A non-Python user can download a release, double-click, and dictate within 2 minutes.

---

## v1.1+ — Backlog (only if missed)

Each item must justify itself by being missed in daily use. Don't pre-build.

- Subscription / OAuth-credit auth path (e.g. "Sign in with ChatGPT" once OpenAI extends the Codex pattern to audio endpoints)
- Hands-free toggle hotkey (tap to start / tap to stop, alongside push-to-talk)
- Persist the recent-transcripts list across restarts
- Per-provider "Test connection" button on the Models page
- Local model warm-up at app start (latency)
- Custom vocabulary / replacements (e.g. "claude" → "Claude")
- Transcript history viewer
- AI rewrite pass (opt-in, using OpenAI/Anthropic)
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
