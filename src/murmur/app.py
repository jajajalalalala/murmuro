"""App controller: wires hotkey → recorder → transcriber → clipboard.

State machine:
    IDLE → RECORDING (hotkey down) → TRANSCRIBING (hotkey up) → IDLE
"""
from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from enum import Enum

from . import config as config_mod
from . import providers as providers_mod
from ._logging import get_logger
from .audio import SAMPLE_RATE, Recorder
from .hotkey import PushToTalkHotkey
from .inject import paste_at_cursor, to_clipboard
from .sounds import play_start, play_stop
from .transcribe import build as build_transcriber

_log = get_logger("app")


class State(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class MurmurApp:
    """Headless controller. UI layers (tray, CLI) subscribe via on_state_change."""

    def __init__(
        self,
        cfg: config_mod.Config,
        on_state_change: Callable[[State], None] | None = None,
        on_result: Callable[[str], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_paste_request: Callable[[str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        # Bind the runtime registry to this Config so list_cloud()
        # surfaces user-added providers from the moment the app starts.
        providers_mod.reload_from_config(cfg)
        self._on_state_change = on_state_change or (lambda _s: None)
        self._on_result = on_result or (lambda _t: None)
        self._on_error = on_error or (lambda _e: None)
        # If provided, the host (tray) marshals the paste onto its UI thread.
        # CGEventPost from a worker thread is silently filtered on Sonoma+
        # for ad-hoc-signed bundles even with Accessibility granted; posting
        # from the same thread that owns the run loop is the only reliable
        # delivery path we've found.
        self._on_paste_request = on_paste_request
        self._recorder = Recorder()
        self._transcriber = None  # lazy
        self._hotkey: PushToTalkHotkey | None = None
        self._state = State.IDLE
        self._lock = threading.Lock()

    @property
    def state(self) -> State:
        return self._state

    @property
    def recorder(self) -> Recorder:
        """Public handle so UI surfaces (e.g. the HUD) can poll
        ``recorder.current_level`` without reaching into private attrs."""
        return self._recorder

    def _set_state(self, s: State) -> None:
        self._state = s
        # Subscribers are best-effort; never let a UI bug crash the audio path.
        with contextlib.suppress(Exception):
            self._on_state_change(s)

    def _ensure_transcriber(self):
        if self._transcriber is None:
            self._transcriber = build_transcriber(self.cfg)
        return self._transcriber

    # --- Hotkey callbacks (run on pynput's listener thread) ---

    def _on_press(self) -> None:
        with self._lock:
            if self._state is not State.IDLE:
                _log.debug("press ignored, state=%s", self._state.value)
                return
            _log.info("press: starting recorder")
            try:
                self._recorder.start()
            except Exception as e:  # noqa: BLE001
                _log.exception("recorder.start() failed")
                self._on_error(e)
                return
            if self.cfg.play_beeps:
                play_start()
            self._set_state(State.RECORDING)

    def _on_release(self) -> None:
        with self._lock:
            if self._state is not State.RECORDING:
                _log.debug("release ignored, state=%s", self._state.value)
                return
            pcm = self._recorder.stop()
            _log.info("release: captured %.2fs of audio", pcm.size / SAMPLE_RATE)
            if self.cfg.play_beeps:
                play_stop()
            self._set_state(State.TRANSCRIBING)

        # Transcribe off the listener thread so we don't block keyboard events.
        threading.Thread(
            target=self._do_transcribe,
            args=(pcm,),
            daemon=True,
        ).start()

    def _do_transcribe(self, pcm) -> None:
        try:
            duration = pcm.size / SAMPLE_RATE
            if duration < 0.2:
                _log.info("clip too short (%.2fs); skipping", duration)
                self._set_state(State.IDLE)
                return
            transcriber = self._ensure_transcriber()
            _log.info("transcribing %.2fs of audio (backend=%s)", duration, self.cfg.backend)
            text = transcriber.transcribe(pcm, SAMPLE_RATE, language=self.cfg.language)
            preview = text if len(text) <= 80 else text[:77] + "..."
            _log.info("transcript: %r", preview)
            if text:
                if self.cfg.auto_paste and self._on_paste_request is not None:
                    # Hand the paste off to the host's UI thread.
                    self._on_paste_request(text)
                elif self.cfg.auto_paste:
                    paste_at_cursor(text)
                else:
                    to_clipboard(text)
                self._on_result(text)
            else:
                _log.info("transcriber returned empty text")
        except Exception as e:  # noqa: BLE001
            _log.exception("transcription failed")
            self._on_error(e)
        finally:
            self._set_state(State.IDLE)

    # --- Lifecycle ---

    def start(self) -> None:
        self._hotkey = PushToTalkHotkey(
            key_spec=self.cfg.hotkey,
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._hotkey.start()

    def stop(self) -> None:
        if self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None

    def reload_config(self, cfg: config_mod.Config) -> None:
        """Apply a new Config in-process.

        Pure-toggle changes (auto_paste, show_hud, play_beeps, language)
        are read at use-time, so they need no rebuild — assigning
        ``self.cfg`` is enough. We only:
          - drop the cached transcriber when backend / cloud_provider_id /
            model actually changed (it lazy-rebuilds on next press);
          - stop and restart the pynput listener when the hotkey spec
            changed.

        This is the entire reload path now — no relaunch happens for any
        save (see #38). pynput stop/start safety on macOS was empirically
        validated in the Phase 1 spike (40 cycles, no exceptions, no thread
        leaks).
        """
        old_cfg = self.cfg
        self.cfg = cfg
        hotkey_changed = old_cfg.hotkey != cfg.hotkey
        transcriber_changed = _transcriber_inputs_changed(old_cfg, cfg)
        _log.debug(
            "reload_config: hotkey_changed=%s, transcriber_changed=%s",
            hotkey_changed,
            transcriber_changed,
        )

        # Always cheap and idempotent: refresh the runtime registry so
        # list_cloud() / list_local() reflect any user-added providers.
        providers_mod.reload_from_config(cfg)

        if transcriber_changed:
            # Force a rebuild on the next push-to-talk.
            self._transcriber = None

        if hotkey_changed and self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None
            self.start()


def _transcriber_inputs_changed(
    old: config_mod.Config, new: config_mod.Config
) -> bool:
    """Return True iff a Config diff implies the cached transcriber is stale.

    A backend or cloud_provider_id flip invalidates regardless of which
    model field is set; otherwise we compare the model field that matches
    the current backend.
    """
    if old.backend != new.backend:
        return True
    if old.cloud_provider_id != new.cloud_provider_id:
        return True
    if old.local.model != new.local.model:
        return True
    return old.openai.model != new.openai.model
