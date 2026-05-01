# Murmur

Murmur is a local-first push-to-talk dictation tool. Hold a hotkey, speak, release — text appears at the cursor. Local Whisper transcription is the primary path; OpenAI-compatible cloud APIs are an optional escape hatch.

## Language

**Recording HUD**:
The small floating overlay shown on screen during the RECORDING state. Frameless, focus-safe (an `NSPanel` with the non-activating style mask on macOS), bottom-anchored. Purely informational — never absorbs input.
_Avoid_: indicator, popup, recorder window, recording icon.

**Active model**:
The single model currently used for transcription. Exactly one is active at any time, regardless of how many are installed or how they're classified (Local / Cloud).
_Avoid_: selected model, current model, default model, in-use model.

**Available model**:
A model the user has installed (downloaded for Local) or configured (API key entered for Cloud). May or may not be the **Active** one.
_Avoid_: ready model, configured model, set up model.

**Catalog**:
The source list of models the user can install from. Composed of (a) curated entries shipped with Murmur, plus (b) user-added entries via "+ Add custom." Both kinds appear identical at the call site once registered.
_Avoid_: model list, library, registry of options.

**Local model**:
A model that runs on-device via `faster-whisper` (CTranslate2). No network call required for transcription.
_Avoid_: offline model, on-device model.

**Cloud model**:
A model that runs via a remote OpenAI-compatible HTTP API (OpenAI, Groq, DeepSeek, MiniMax, user-added endpoints). Requires an API key and network access.
_Avoid_: remote model, online model, API model.

**Provider**:
A service that hosts one or more **Cloud models**. Identified by `(display_name, base_url)` plus an API key. Curated providers ship in `providers.py`; custom providers are user-added.
_Avoid_: vendor, host, endpoint.

**Push-to-talk hotkey**:
The keyboard combination held to record. Pynput-spec format (e.g. `<right_alt>`, `<ctrl>+<shift>+<space>`). Modifier-only specs commit on release; combos with a non-modifier commit on the non-modifier press.
_Avoid_: shortcut, key binding, trigger key.

## Relationships

- The **Catalog** lists potential models; an **Available model** is one the user has installed *from* the catalog (or added custom)
- An **Active model** is exactly one **Available model** chosen for use; switching it is a deliberate "Use" click in the Models page, never automatic
- A **Cloud model** belongs to exactly one **Provider**; a **Provider** can host multiple **Cloud models**
- The **Recording HUD** is shown during the RECORDING state of the app's state machine and hides on every other state

## Example dialogue

> **Dev:** "If the user has Groq configured and downloads a new local model, does the local one become **Active**?"
> **Maintainer:** "No — installing or configuring is **Available**, never **Active**. Active changes only when the user clicks Use."

> **Dev:** "Should custom **Providers** appear in the same list as curated ones?"
> **Maintainer:** "Yes. Once added they go into the **Catalog** and look identical at the call site. The form to *add* them is different — curated cards show only the API key field, custom adds Display name + URL + Model + Key — but the resulting row in the registry is the same shape."

## Flagged ambiguities

- **"icon" used loosely for both the tray glyph and the Recording HUD.** Resolved: `tray icon` always refers to the menu-bar / system-tray glyph; `Recording HUD` is the floating overlay. Never use bare "icon" for either.
- **"install" used loosely for both downloading a Local model and configuring a Cloud one.** Resolved: "install" is acceptable for both at the user-visible level (the Models page calls both *Install*), but at the code level use `download` for Local and `configure` for Cloud — they touch different code paths (HuggingFace cache vs. keychain + provider registry).
- **"Save" vs "Activate".** Resolved: Saving a model (after a successful test, for cloud, or after a successful download, for local) makes it **Available**. Clicking **Use** makes it **Active**. The two are deliberately separate clicks — never collapsed.
