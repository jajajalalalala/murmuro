"""User configuration loaded from a TOML file in the platform config dir."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w
import tomllib
from platformdirs import user_config_dir

APP_NAME = "Murmur"


@dataclass
class LocalBackendConfig:
    # Empty by default — a fresh install ships with no model selected so
    # the first push-to-talk doesn't silently pull ~145 MB from
    # HuggingFace. The user picks a model on the Models page; until then
    # transcribe.factory.build raises a clear error and the UI nudges
    # them toward it.
    model: str = ""
    device: str = "auto"
    compute_type: str = "int8"
    # Where faster-whisper writes downloaded model files. Empty string
    # means "use the platformdirs default" (resolved at the call site
    # via transcribe.factory._resolve_local_download_root). Persisting
    # the empty default keeps existing TOML files unchanged across the
    # v0.5 → v0.6 path move.
    download_root: str = ""


@dataclass
class OpenAIBackendConfig:
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "whisper-1"


@dataclass
class CustomCloudProvider:
    """User-added OpenAI-compatible cloud provider.

    Persisted under ``[[custom_cloud]]`` in ``config.toml``. The API key
    is **never** stored here — it lives in the OS keychain under
    ``provider_id``. See ADR-0001 and ``murmur.secrets``.

    ``api_key_env`` defaults to ``<PROVIDER_ID>_API_KEY`` (matching
    ``murmur.secrets``'s default rule), but can be overridden so users
    with a non-conforming env var name (e.g. someone who already exports
    ``MINIMAX_TOKEN``) can keep using it.
    """

    provider_id: str
    display_name: str
    base_url: str
    model: str
    api_key_env: str = ""


@dataclass
class Config:
    # Two-axis backend selection:
    #   ``backend`` is "local" or "cloud" (was "openai" before #17 — see
    #   ``load`` for the transparent migration). When "cloud",
    #   ``cloud_provider_id`` picks which entry from
    #   ``providers.list_cloud()`` to dispatch to.
    backend: str = "local"
    cloud_provider_id: str = "openai"
    language: str = "auto"
    hotkey: str = "<right_alt>"
    auto_paste: bool = True
    # Floating "Recording…" pill at the top of the screen. Even with
    # Qt.Tool | WindowDoesNotAcceptFocus | WA_ShowWithoutActivating, the
    # underlying NSPanel can briefly become key on macOS Sonoma+ when the
    # owning process is LSUIElement, which breaks auto-paste by stealing
    # focus from whatever text field the user is typing into. Off lets us
    # confirm whether that's the culprit and gives users a way to dictate
    # without any visible window changing focus.
    show_hud: bool = True
    # Short audible cue when recording starts/stops. Defaults to on so
    # the user gets immediate, eyes-free confirmation that the hotkey
    # registered — independent of the on-screen HUD.
    play_beeps: bool = True
    # UI theme. Off (default) = light mode; on = dark mode. Persisted so
    # the user's choice survives a relaunch instead of falling back to
    # auto-detect each time.
    dark_mode: bool = False
    local: LocalBackendConfig = field(default_factory=LocalBackendConfig)
    openai: OpenAIBackendConfig = field(default_factory=OpenAIBackendConfig)
    # User-added cloud providers (curated entries live in
    # ``providers._CURATED_CLOUD`` and are not duplicated here).
    custom_cloud: list[CustomCloudProvider] = field(default_factory=list)


def config_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "config.toml"


def load() -> Config:
    path = config_path()
    if not path.exists():
        cfg = Config()
        save(cfg)
        return cfg
    with path.open("rb") as f:
        data = tomllib.load(f)
    backend = data.get("backend", "local")
    cloud_provider_id = data.get("cloud_provider_id", "openai")
    # Backwards compat: pre-#17 configs used backend = "openai" to mean
    # "the OpenAI cloud provider". Translate transparently so existing
    # users keep working without editing their TOML by hand.
    if backend == "openai":
        backend = "cloud"
        cloud_provider_id = "openai"
    cfg = Config(
        backend=backend,
        cloud_provider_id=cloud_provider_id,
        language=data.get("language", "auto"),
        hotkey=data.get("hotkey", "<right_alt>"),
        auto_paste=data.get("auto_paste", True),
        show_hud=data.get("show_hud", True),
        play_beeps=data.get("play_beeps", True),
        dark_mode=data.get("dark_mode", False),
        local=LocalBackendConfig(**data.get("local", {})),
        openai=OpenAIBackendConfig(**data.get("openai", {})),
        custom_cloud=[
            CustomCloudProvider(**c) for c in data.get("custom_cloud", [])
        ],
    )
    return cfg


def save(cfg: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(asdict(cfg), f)
