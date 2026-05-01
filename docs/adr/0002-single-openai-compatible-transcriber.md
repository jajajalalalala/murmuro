# Single OpenAI-compatible class for all cloud transcription

All cloud transcription backends (OpenAI, Groq, DeepSeek, MiniMax, user-added custom endpoints) are served by a single class in `src/murmur/transcribe/openai_compatible.py` constructed with `(base_url, api_key, model)`. The class uses the official `openai` SDK with the `base_url=` parameter set per provider.

## Considered options

- **Per-provider classes.** One class per cloud (`OpenAIWhisper`, `GroqWhisper`, `DeepSeekWhisper`, ...). Maximum flexibility — each can override request shape, error handling, retries. The factory dispatches by provider name. Rejected: every provider supported today (and the user-added "+ Add custom" path) speaks the same OpenAI-compatible HTTP shape, so per-provider classes would be near-duplicates dressed in different filenames.
- **Single config-driven class (chosen).** One class, the only varying input is the constructor tuple. The factory dispatches on `cfg.backend`: `local` → `LocalWhisper`, anything else → `OpenAICompatible(base_url=..., api_key=..., model=...)`. The "+ Add custom" form maps directly to the constructor — no new code is needed to support a new OpenAI-compatible vendor.

## Why

The provider expansion plan (Groq, DeepSeek, MiniMax-class custom endpoints) already required writing one path that took a base URL and a model name from config. Per-provider classes would have produced N near-duplicate files that we'd later collapse anyway. Doing the collapse upfront unblocks the "+ Add custom" UI path with no extra code, and means new vendors arrive as one row in `providers.py` rather than a new module.

## Consequences

If a future provider needs a non-OpenAI-compatible request shape (different multipart layout, custom auth header, streaming response), the single class no longer suffices and we'd grow back to a per-provider shape. That's accepted — at the point a non-compliant provider matters, the cost of refactoring is worth the present simplicity.
