# Architecture

## Data flow

```
   ┌────────────┐    PCM    ┌──────────────┐   text   ┌─────────────┐
   │  hotkey    ├──────────▶│  transcriber │─────────▶│   inject    │
   │ (push-to-  │           │ (local /     │          │ (paste at   │
   │  talk)     │           │  openai api) │          │  cursor)    │
   └─────┬──────┘           └──────────────┘          └─────────────┘
         │ start/stop
         ▼
   ┌────────────┐
   │   audio    │
   │ (sounddev.)│
   └────────────┘

   tray icon ◀── state events from app controller
```

## Modules

| Module | Responsibility | Key deps |
|---|---|---|
| `audio.py` | Capture mic → 16 kHz mono PCM buffer | `sounddevice`, `numpy` |
| `hotkey.py` | OS-level push-to-talk listener | `pynput` |
| `hotkey_recorder.py` | Click-to-record QWidget capturing hotkey by pressing it | `PySide6` |
| `transcribe/base.py` | `Transcriber` Protocol | — |
| `transcribe/local.py` | `faster-whisper` backend, lazy load | `faster-whisper` |
| `transcribe/openai_compatible.py` | OpenAI-compatible cloud backend (OpenAI, Groq, DeepSeek, custom) | `openai` |
| `transcribe/factory.py` | Build a `Transcriber` from a `Config` | — |
| `inject.py` | Copy + CGEventPost ⌘V (mac) / `pynput` paste (win) | `pyperclip`, `pynput`, `ctypes` |
| `hud.py` | Floating recording pill; non-activating NSPanel via pyobjc | `PySide6`, `pyobjc-framework-Cocoa` |
| `tray.py` | Menu bar tray icon, state UI, opens main window | `PySide6` (QSystemTrayIcon) |
| `main_window.py` | `QMainWindow` shell: left rail + stacked pages | `PySide6` |
| `pages/home.py` | Status, recent transcripts, auto-paste / HUD / language | `PySide6` |
| `pages/shortcuts.py` | Push-to-talk hotkey row | `PySide6` |
| `pages/models.py` | Provider dropdown + Local model list + Cloud auth panel | `PySide6` |
| `providers.py` | `LocalModel` + `CloudProvider` registry | — |
| `permissions.py` | macOS TCC checks + System Settings deep-links | `pyobjc-framework-ApplicationServices` |
| `config.py` | TOML config in `platformdirs.user_config_dir` | `platformdirs`, `tomli-w` |
| `app.py` | Wires everything; state machine; paste-routing callback | — |
| `__main__.py` | Entrypoint: GUI or `--cli` mode | — |

## State machine

```
IDLE ──hotkey-down──▶ RECORDING ──hotkey-up──▶ TRANSCRIBING ──result──▶ INJECTING ──▶ IDLE
                          │                          │                       │
                          └─────── Esc ──────────────┴───── error ───────────┘
                                                                             ▼
                                                                           IDLE
```

## Cross-platform notes

| Concern | macOS | Windows |
|---|---|---|
| Mic permission | TCC prompt on first record | UAC-free |
| Global hotkey | `pynput.keyboard.GlobalHotKeys`; `fn` key not capturable → fall back to `right_option` | `pynput` works for most keys |
| Paste | `cmd+v` via `pynput` | `ctrl+v` via `pynput` |
| Tray icon | `QSystemTrayIcon`; hide Dock with `LSUIElement=true` in plist | `QSystemTrayIcon` works natively |
| Packaging | `pyinstaller --windowed` → `.app` | `pyinstaller` → `.exe` + installer |

## Backend interface

```python
# transcribe/base.py
class Transcriber(Protocol):
    def transcribe(self, pcm: np.ndarray, sample_rate: int, language: str | None) -> str: ...
```

Adding a new backend = one file implementing this Protocol + one entry in `config.backend`.

## Config schema

```toml
# ~/Library/Application Support/Murmur/config.toml  (mac)
# %APPDATA%\Murmur\config.toml                       (windows)

backend = "local"          # "local" | "openai"
language = "auto"          # ISO 639-1 or "auto"
hotkey = "<right_alt>"     # pynput hotkey syntax
auto_paste = true

[local]
model = "base"             # tiny | base | small | medium | large-v3
device = "auto"            # auto | cpu | cuda | mps
compute_type = "int8"      # int8 | float16 | float32

[openai]
api_key_env = "OPENAI_API_KEY"
model = "whisper-1"
```

## Why these choices

- **Python**: fastest iteration, mature audio + Whisper + hotkey libraries, easy for the owner to modify.
- **PySide6 over Tkinter**: `QSystemTrayIcon` is the cleanest cross-platform tray API.
- **`faster-whisper` over `openai-whisper`**: 4× faster on CPU via CTranslate2, smaller memory footprint.
- **`pynput` over `keyboard`**: works without root on macOS; `keyboard` requires sudo.
- **TOML config over JSON**: human-edited config, comments allowed.
