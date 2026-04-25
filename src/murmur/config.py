"""User configuration loaded from a TOML file in the platform config dir."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path

import tomli_w
from platformdirs import user_config_dir

APP_NAME = "Murmur"


@dataclass
class LocalBackendConfig:
    model: str = "base"
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
        local=LocalBackendConfig(**data.get("local", {})),
        openai=OpenAIBackendConfig(**data.get("openai", {})),
    )
    return cfg


def save(cfg: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(asdict(cfg), f)


def openai_api_key(cfg: Config) -> str | None:
    return os.environ.get(cfg.openai.api_key_env)
