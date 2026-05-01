# Security

Murmuro is a personal dictation tool that runs locally and stores data only on your machine. There is no server, no telemetry, no account, and no shared infrastructure.

## What Murmuro stores

| Item | Where |
|---|---|
| Config (hotkey, language, selected model, etc.) | `~/Library/Application Support/Murmuro/config.toml` (macOS) |
| Logs | `~/Library/Logs/Murmuro/murmuro.log` (macOS) |
| Cloud-provider API keys | Your OS keychain via the [`keyring`](https://pypi.org/project/keyring/) library, with a per-provider env-var fallback. Never written to the config file. |
| Whisper model weights | The HuggingFace cache (`~/.cache/huggingface/hub/`) for legacy installs, or `~/Library/Application Support/Murmuro/models/` for v0.6+ installs. |
| Audio recordings | Held in memory only — never written to disk. |
| Transcripts | The most recent 5 are kept in memory for the Home page; not persisted across restarts. |

`murmuro --uninstall` removes the config, logs, and Murmuro-managed Whisper caches. Other HuggingFace models are left alone.

## Reporting a vulnerability

If you find a security issue (credential leak, sandbox escape, anything that could harm a user's system or data), please **do not file a public GitHub issue**.

Instead, email the maintainer directly: **lalalajajaja188@gmail.com**

Include:
- A description of the issue and the impact
- Steps to reproduce, if you have them
- The Murmuro version (`murmuro --version` or About page)

I'll respond within a week. For non-security bugs, please use the [issue tracker](https://github.com/jajajalalalala/murmuro/issues) instead.

## Distribution security

Murmuro v1.0 ships ad-hoc-signed (not Apple-notarized). The `xattr -dr com.apple.quarantine` step in the install instructions is required to launch the downloaded `.app` — see the [README](README.md#why-the-quarantine-bypass) for the full explanation.

If you'd rather not run that command, you can [build from source](README.md#from-source) — local builds are not quarantined.

Real Apple Developer-ID notarization is on the [v1.1+ roadmap](ROADMAP.md). It removes the quarantine step entirely and lets Gatekeeper verify each release was produced by the same identity.
