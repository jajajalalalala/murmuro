"""MurmuroApp.reload_config is selective.

Pure toggle saves (auto_paste, show_hud, play_beeps, language) must
not touch the hotkey listener and must not drop the cached transcriber.
Backend / cloud_provider_id / model changes drop the cached transcriber
so the next press rebuilds it. Hotkey changes are applied via a
user-confirmed restart in the main window — they do NOT call into the
running listener (#38), so reload_config is a no-op for that axis.
"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

from murmuro.app import MurmuroApp, _transcriber_inputs_changed
from murmuro.config import Config, LocalBackendConfig, OpenAIBackendConfig


def _build_app(cfg: Config) -> MurmuroApp:
    """Build a MurmuroApp with a fake recorder + a mock pynput hotkey already attached."""
    with patch("murmuro.app.Recorder", return_value=MagicMock()):
        app = MurmuroApp(cfg=cfg)
    # Skip a real PushToTalkHotkey; tests inspect stop() and start() directly.
    app._hotkey = MagicMock()
    # Pretend a transcriber has been lazily built so we can detect when it gets dropped.
    sentinel_transcriber = object()
    app._transcriber = sentinel_transcriber
    return app


def test_pure_toggle_save_does_not_touch_hotkey_or_transcriber():
    cfg = Config()
    app = _build_app(cfg)
    pre_hotkey = app._hotkey
    pre_transcriber = app._transcriber

    new_cfg = replace(cfg, auto_paste=not cfg.auto_paste)
    with patch.object(MurmuroApp, "start") as start_mock:
        app.reload_config(new_cfg)

    pre_hotkey.stop.assert_not_called()
    assert app._hotkey is pre_hotkey, "hotkey should not be replaced for toggle save"
    assert app._transcriber is pre_transcriber, "transcriber should be retained"
    start_mock.assert_not_called()
    assert app.cfg is new_cfg


def test_show_hud_toggle_does_not_touch_hotkey_or_transcriber():
    cfg = Config()
    app = _build_app(cfg)
    pre_hotkey = app._hotkey
    pre_transcriber = app._transcriber

    new_cfg = replace(cfg, show_hud=not cfg.show_hud)
    with patch.object(MurmuroApp, "start") as start_mock:
        app.reload_config(new_cfg)

    pre_hotkey.stop.assert_not_called()
    assert app._transcriber is pre_transcriber
    start_mock.assert_not_called()


def test_hotkey_change_is_a_noop_for_the_running_listener():
    """Hotkey rebinding lives in the main-window restart modal, not here.
    reload_config must not stop, start, or replace_spec the listener for
    a hotkey change — both prior attempts to do so failed in production."""
    cfg = Config(hotkey="<right_alt>")
    app = _build_app(cfg)
    pre_hotkey = app._hotkey
    pre_transcriber = app._transcriber

    new_cfg = replace(cfg, hotkey="<f13>")
    with patch.object(MurmuroApp, "start") as start_mock:
        app.reload_config(new_cfg)

    pre_hotkey.stop.assert_not_called()
    pre_hotkey.replace_spec.assert_not_called()
    start_mock.assert_not_called()
    assert app._hotkey is pre_hotkey
    # Hotkey change alone must not invalidate the transcriber.
    assert app._transcriber is pre_transcriber
    # Config is still updated — the modal will read it on relaunch.
    assert app.cfg.hotkey == "<f13>"


def test_local_model_change_drops_transcriber_only():
    cfg = Config(backend="local", local=LocalBackendConfig(model="tiny"))
    app = _build_app(cfg)
    pre_hotkey = app._hotkey

    new_cfg = replace(cfg, local=LocalBackendConfig(model="small"))
    with patch.object(MurmuroApp, "start") as start_mock:
        app.reload_config(new_cfg)

    assert app._transcriber is None
    pre_hotkey.stop.assert_not_called()
    start_mock.assert_not_called()


def test_cloud_provider_change_drops_transcriber_only():
    cfg = Config(backend="cloud", cloud_provider_id="openai")
    app = _build_app(cfg)
    pre_hotkey = app._hotkey

    new_cfg = replace(cfg, cloud_provider_id="groq")
    with patch.object(MurmuroApp, "start") as start_mock:
        app.reload_config(new_cfg)

    assert app._transcriber is None
    pre_hotkey.stop.assert_not_called()
    start_mock.assert_not_called()


def test_backend_switch_local_to_cloud_drops_transcriber_only():
    cfg = Config(backend="local")
    app = _build_app(cfg)
    pre_hotkey = app._hotkey

    new_cfg = replace(cfg, backend="cloud")
    with patch.object(MurmuroApp, "start") as start_mock:
        app.reload_config(new_cfg)

    assert app._transcriber is None
    pre_hotkey.stop.assert_not_called()
    start_mock.assert_not_called()


def test_openai_model_change_drops_transcriber():
    cfg = Config(backend="cloud", openai=OpenAIBackendConfig(model="whisper-1"))
    app = _build_app(cfg)

    new_cfg = replace(cfg, openai=OpenAIBackendConfig(model="whisper-large-v3"))
    with patch.object(MurmuroApp, "start") as start_mock:
        app.reload_config(new_cfg)

    assert app._transcriber is None
    start_mock.assert_not_called()


def test_combined_hotkey_and_model_change_drops_transcriber_only():
    """Combined save: model change drops transcriber, hotkey change is
    a no-op here (handled by the main-window modal)."""
    cfg = Config(
        backend="local",
        hotkey="<right_alt>",
        local=LocalBackendConfig(model="tiny"),
    )
    app = _build_app(cfg)
    pre_hotkey = app._hotkey

    new_cfg = replace(
        cfg,
        hotkey="<f13>",
        local=LocalBackendConfig(model="small"),
    )
    with patch.object(MurmuroApp, "start") as start_mock:
        app.reload_config(new_cfg)

    pre_hotkey.stop.assert_not_called()
    start_mock.assert_not_called()
    assert app._transcriber is None


def test_reload_config_always_refreshes_provider_registry():
    """providers_mod.reload_from_config is cheap + idempotent — always run it."""
    cfg = Config()
    app = _build_app(cfg)

    new_cfg = replace(cfg, auto_paste=not cfg.auto_paste)
    with (
        patch.object(MurmuroApp, "start"),
        patch("murmuro.app.providers_mod.reload_from_config") as reload_registry,
    ):
        app.reload_config(new_cfg)

    reload_registry.assert_called_once_with(new_cfg)


# --- Helper coverage ---------------------------------------------------------

def test_transcriber_inputs_changed_detects_each_axis():
    base = Config()
    assert _transcriber_inputs_changed(base, base) is False
    assert _transcriber_inputs_changed(base, replace(base, backend="cloud")) is True
    assert (
        _transcriber_inputs_changed(base, replace(base, cloud_provider_id="groq"))
        is True
    )
    assert (
        _transcriber_inputs_changed(
            base, replace(base, local=LocalBackendConfig(model="small"))
        )
        is True
    )
    assert (
        _transcriber_inputs_changed(
            base, replace(base, openai=OpenAIBackendConfig(model="whisper-large-v3"))
        )
        is True
    )
    # Pure toggles must not register as transcriber-impacting.
    assert (
        _transcriber_inputs_changed(base, replace(base, auto_paste=not base.auto_paste))
        is False
    )
    assert (
        _transcriber_inputs_changed(base, replace(base, show_hud=not base.show_hud))
        is False
    )
    assert _transcriber_inputs_changed(base, replace(base, language="en")) is False
    assert (
        _transcriber_inputs_changed(base, replace(base, hotkey="<f13>")) is False
    )
