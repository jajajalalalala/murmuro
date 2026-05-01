# API key storage: OS keychain primary, env-var fallback

Cloud-provider API keys (OpenAI, Groq, DeepSeek, custom OpenAI-compatible endpoints) are stored in the OS keychain via the `keyring` library. If the keychain has no entry for a given provider, Murmur falls back to reading a per-provider environment variable (e.g. `GROQ_API_KEY`).

## Considered options

- **Env-var only.** `cfg.cloud[provider].api_key_env: str` names the env var; Murmur reads `os.environ[...]` at runtime. Simplest. Murmur never stores secrets. Hostile to non-technical users — they can't `export GROQ_API_KEY=...` in a shell rc file.
- **Inline keys, stored in `config.toml`.** Best UX, worst security: keys live in plaintext in the user's app data dir. Leaks via backups (iCloud, Time Machine), debugging shares (`config.toml` pasted into a GitHub issue), and any process running as the user.
- **Inline keys, stored in OS keychain (chosen).** UI-friendly: paste key into the Models page, it lands in macOS Keychain / Windows Credential Manager. The TOML config only stores a reference ID. Adds a single dependency (`keyring`) and a local secrets module that owns the precedence rules.
- **Both keychain and env-var.** Chosen with a one-way precedence: keychain reads first, env-var second. Power users (1Password CLI, direnv, shell rc) keep working without touching the UI; everyone else uses the UI. Not exposed as a user-facing radio button — the precedence is internal.

## Why

Murmur's stated audience includes non-technical users. Forcing them through env vars to use any cloud provider would be hostile. Forcing keys into plaintext on disk would be a backup-leakage / debugging-share liability that's hard to revisit once shipped. The keychain-with-env-var-fallback rule covers both audiences with one read path and ~50 lines of `secrets.py`.
