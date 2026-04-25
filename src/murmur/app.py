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
from ._logging import get_logger
from .audio import SAMPLE_RATE, Recorder
from .hotkey import PushToTalkHotkey
from .inject import paste_at_cursor, to_clipboard
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
    ) -> None:
        self.cfg = cfg
        self._on_state_change = on_state_change or (lambda _s: None)
        self._on_result = on_result or (lambda _t: None)
        self._on_error = on_error or (lambda _e: None)
        self._recorder = Recorder()
        self._transcriber = None  # lazy
        self._hotkey: PushToTalkHotkey | None = None
        self._state = State.IDLE
        self._lock = threading.Lock()

    @property
    def state(self) -> State:
        return self._state

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
            self._set_state(State.RECORDING)

    def _on_release(self) -> None:
        with self._lock:
            if self._state is not State.RECORDING:
                _log.debug("release ignored, state=%s", self._state.value)
                return
            pcm = self._recorder.stop()
            _log.info("release: captured %.2fs of audio", pcm.size / SAMPLE_RATE)
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
                if self.cfg.auto_paste:
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
        """Apply a new Config: rebind the hotkey, drop the cached transcriber.

        The transcriber re-builds lazily on the next push-to-talk, so a
        backend/model change becomes visible without an app restart.
        """
        self.cfg = cfg
        self._transcriber = None  # force rebuild on next press
        if self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None
        self.start()
