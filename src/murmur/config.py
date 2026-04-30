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


@dataclass
class OpenAIBackendConfig:
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "whisper-1"


@dataclass
class Config:
    backend: str = "local"
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
    local: LocalBackendConfig = field(default_factory=LocalBackendConfig)
    openai: OpenAIBackendConfig = field(default_factory=OpenAIBackendConfig)


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
    cfg = Config(
        backend=data.get("backend", "local"),
        language=data.get("language", "auto"),
        hotkey=data.get("hotkey", "<right_alt>"),
        auto_paste=data.get("auto_paste", True),
        show_hud=data.get("show_hud", True),
        play_beeps=data.get("play_beeps", True),
        local=LocalBackendConfig(**data.get("local", {})),
        openai=OpenAIBackendConfig(**data.get("openai", {})),
    )
    return cfg


def save(cfg: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(asdict(cfg), f)
