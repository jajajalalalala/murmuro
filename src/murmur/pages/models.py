"""Models page: pick the transcription backend.

Top-level dropdown chooses between Local (on-device) and any registered
cloud provider. Picking Local reveals a list of faster-whisper models with
size + Download/Use controls. Picking a cloud provider reveals an API
key field plus that provider's available models.

Downloads run in a worker thread so the UI doesn't freeze on the first
multi-hundred-MB pull. Per-row progress is intentionally coarse (a
spinner + state label) — faster-whisper's WhisperModel constructor doesn't
expose progress callbacks, so anything finer would require shelling out
to ``huggingface_hub`` directly. Trade-off accepted for simplicity.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config as config_mod
from .. import providers as providers_mod
from .. import secrets
from .._logging import get_logger
from ..providers import CloudProvider, LocalModel, find_local_model
from ..transcribe.factory import _resolve_local_download_root
from ..ui.theme import card, destructive_button, primary_button, section_label

_log = get_logger("models_page")


# ---- Worker for blocking faster-whisper downloads -----------------------------

class _DownloadWorker(QObject):
    """Materialize a faster-whisper model in its own thread.

    Instantiating ``WhisperModel(name)`` triggers the HuggingFace download
    if the model isn't cached. The constructor is blocking and noisy, so
    we run it off the UI thread and let the UI listen for ``finished``.
    """

    finished = Signal(str, bool, str)  # (model_id, ok, error_message)

    def __init__(self, model_id: str, download_root: str) -> None:
        super().__init__()
        self.model_id = model_id
        self.download_root = download_root

    def run(self) -> None:
        try:
            from faster_whisper import WhisperModel

            # device=cpu, compute_type=int8 is the cheapest "just download"
            # combo that works on every machine. Real transcription uses
            # the user's chosen device/compute_type from cfg.local.
            WhisperModel(
                self.model_id,
                device="cpu",
                compute_type="int8",
                download_root=self.download_root,
            )
        except Exception as e:  # noqa: BLE001
            _log.exception("download failed for %s", self.model_id)
            self.finished.emit(self.model_id, False, str(e))
            return
        self.finished.emit(self.model_id, True, "")


# ---- Local model row ----------------------------------------------------------

class _LocalModelRow(QFrame):
    """One row per faster-whisper model: label, size, Download/Use button."""

    download_requested = Signal(str)   # model_id
    use_requested = Signal(str)        # model_id
    delete_requested = Signal(str)     # model_id

    # Fixed widths for the trailing columns so every row's status text,
    # primary action, and delete button line up vertically — even when
    # one row is "Active / In use" and another is "Not downloaded /
    # Download". Without these, each row sized its own controls
    # independently and the page looked uneven.
    _STATUS_WIDTH = 110
    _ACTION_WIDTH = 110
    _DELETE_WIDTH = 80

    def __init__(
        self,
        model: LocalModel,
        download_root: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = model
        # Murmur-private download root resolved by the factory. Stored on
        # each row so cache_path()/is_downloaded() always look in the new
        # location instead of the legacy HF cache.
        self.download_root = download_root
        self.setProperty("card", True)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(12)

        title = QLabel(f"<b>{model.label}</b>")
        meta_bits = [_format_size(model.size_mb)]
        meta_bits.append("Multilingual" if model.multilingual else "English-only")
        meta = QLabel("  ·  ".join(meta_bits))
        meta.setProperty("dim", True)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(title)
        text_col.addWidget(meta)
        # Optional one-line tagline under the size/flavor row. Wraps so
        # longer guidance ("Slower start; needs ~3 GB RAM headroom.")
        # doesn't blow out the row width.
        if model.tagline:
            tag = QLabel(model.tagline)
            tag.setProperty("dim", True)
            tag.setWordWrap(True)
            text_col.addWidget(tag)

        self._status = QLabel()
        self._status.setProperty("hint", True)
        self._status.setFixedWidth(self._STATUS_WIDTH)
        self._status.setAlignment(_qt_right_center())

        # Inline progress bar — hidden until a download is in flight.
        # Same fixed width as the status column so swapping between
        # them doesn't shift the surrounding controls horizontally.
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFixedWidth(self._STATUS_WIDTH)
        self._progress.setVisible(False)

        self._action = primary_button("")
        self._action.setFixedWidth(self._ACTION_WIDTH)
        self._action.clicked.connect(self._on_action)

        # Secondary "Delete" button: removes the on-disk model files.
        # Always reserves its slot via fixed width — invisible when not
        # applicable, so the action button next door never shifts as
        # rows enter/leave the downloaded state.
        self._delete = destructive_button("Delete")
        self._delete.setFixedWidth(self._DELETE_WIDTH)
        self._delete.clicked.connect(self._on_delete)
        # Use opacity-style hide via a placeholder so the row keeps
        # its width: setVisible(False) collapses the slot, but we want
        # the slot reserved. The simplest hack is to keep the button
        # visible but disable it and clear its text — done in _refresh.

        row.addLayout(text_col, 1)
        row.addWidget(self._status)
        row.addWidget(self._progress)
        row.addWidget(self._action)
        row.addWidget(self._delete)

        self._is_active = False
        self._is_downloading = False
        self._refresh()

    # Public state hooks -------------------------------------------------

    def set_active(self, active: bool) -> None:
        self._is_active = active
        self._refresh()

    def set_downloading(self, downloading: bool) -> None:
        self._is_downloading = downloading
        if not downloading:
            self._progress.setVisible(False)
            self._progress.setValue(0)
        self._refresh()

    def set_progress(self, fraction: float) -> None:
        """Push a 0.0–1.0 progress estimate into the inline bar.

        Polled from the cache directory size; values are best-effort,
        so we clamp to [0, 99] until the worker reports completion.
        """
        if not self._is_downloading:
            return
        pct = max(0, min(99, int(fraction * 100)))
        self._progress.setVisible(True)
        self._status.setVisible(False)
        self._progress.setValue(pct)
        self._progress.setFormat(f"{pct}%")

    def refresh_download_state(self) -> None:
        """Re-check disk so a freshly-finished download flips to Use."""
        self._refresh()

    # -------------------------------------------------------------------

    def _on_action(self) -> None:
        if self._is_downloading:
            return
        if self.model.is_downloaded(self.download_root):
            self.use_requested.emit(self.model.id)
        else:
            self.download_requested.emit(self.model.id)

    def _on_delete(self) -> None:
        if self._is_downloading or self._is_active:
            return
        if not self.model.is_downloaded(self.download_root):
            return
        self.delete_requested.emit(self.model.id)

    def _refresh(self) -> None:
        downloaded = self.model.is_downloaded(self.download_root)
        if self._is_downloading:
            self._action.setEnabled(False)
            self._action.setText("Downloading…")
            self._set_delete_inactive()
            # Show "Fetching…" until the first poll arrives with a real
            # percentage; from then on _set_progress takes over.
            if self._progress.value() == 0:
                self._status.setVisible(True)
                self._progress.setVisible(False)
                self._status.setText("Fetching from HuggingFace")
            return
        self._status.setVisible(True)
        self._action.setEnabled(True)
        if not downloaded:
            self._action.setText("Download")
            self._status.setText("Not downloaded")
            self._set_delete_inactive()
            return
        # Downloaded — Delete becomes a real button. It's disabled when
        # this row is the active model so the user can't yank the
        # backend out from under a live transcribe call; switching to
        # another model re-enables.
        if self._is_active:
            self._action.setText("In use")
            self._action.setEnabled(False)
            self._status.setText("Active")
            self._set_delete_inactive(
                tooltip="Switch to another model first, then delete this one.",
            )
        else:
            self._action.setText("Use")
            self._status.setText("Downloaded")
            self._delete.setText("Delete")
            self._delete.setEnabled(True)
            # Use a Qt graphics-effect-free transparent state via stylesheet
            # property; restore opaque appearance.
            self._delete.setProperty("placeholder", False)
            self._delete.style().unpolish(self._delete)
            self._delete.style().polish(self._delete)
            self._delete.setToolTip("")

    def _set_delete_inactive(self, tooltip: str = "") -> None:
        """Render the Delete slot as a non-clickable placeholder.

        Keeps the row's column geometry stable: the Delete button
        always occupies its fixed-width slot, but it's invisible when
        not applicable so it doesn't compete with the primary action.
        """
        self._delete.setText("")
        self._delete.setEnabled(False)
        self._delete.setProperty("placeholder", True)
        self._delete.style().unpolish(self._delete)
        self._delete.style().polish(self._delete)
        self._delete.setToolTip(tooltip)


# ---- Local panel --------------------------------------------------------------

class _LocalPanel(QWidget):
    """List of LocalModelRow plus thread/worker bookkeeping."""

    model_selected = Signal(str)  # active model id changed

    POLL_INTERVAL_MS = 500  # how often to recheck cache-dir size during download

    def __init__(self, cfg: config_mod.Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._rows: dict[str, _LocalModelRow] = {}
        self._active_model_id = cfg.local.model
        self._workers: dict[str, tuple[QThread, _DownloadWorker]] = {}
        # Resolve the Murmur-private download root once; the panel
        # passes it down to every row + worker so they all agree on
        # where models live on disk. Creates the directory if missing.
        self._download_root = _resolve_local_download_root(cfg)

        # Single timer drives every in-flight progress bar — faster-whisper's
        # constructor is opaque, so we estimate progress by polling the size
        # of the on-disk model directory against the model's known total.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_progress)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        for model in providers_mod.list_local():
            row = _LocalModelRow(model, self._download_root)
            row.download_requested.connect(self._start_download)
            row.use_requested.connect(self._select_model)
            row.delete_requested.connect(self._delete_model)
            layout.addWidget(row)
            self._rows[model.id] = row

        # Custom-model rows aren't shipped in the registry but the user may
        # have entered one in the TOML by hand — keep it visible/active.
        # Skip when the model is empty: a fresh install starts with no
        # selection, and we don't want to render a "(custom)" row labelled "".
        if cfg.local.model and cfg.local.model not in self._rows:
            custom = LocalModel(
                id=cfg.local.model,
                label=cfg.local.model + " (custom)",
                size_mb=0,
                multilingual=True,
            )
            row = _LocalModelRow(custom, self._download_root)
            row.use_requested.connect(self._select_model)
            row.delete_requested.connect(self._delete_model)
            layout.addWidget(row)
            self._rows[custom.id] = row

        layout.addStretch(1)
        self._refresh_active()

    # Public ------------------------------------------------------------

    @property
    def active_model_id(self) -> str:
        return self._active_model_id

    def set_config(self, cfg: config_mod.Config) -> None:
        self._cfg = cfg
        self._active_model_id = cfg.local.model
        # Re-resolve in case the user pointed Murmur at a different
        # download_root via the TOML; rows pick up the new path on the
        # next refresh / action.
        self._download_root = _resolve_local_download_root(cfg)
        for row in self._rows.values():
            row.download_root = self._download_root
        self._refresh_active()

    # Internals ---------------------------------------------------------

    def _select_model(self, model_id: str) -> None:
        self._active_model_id = model_id
        self._refresh_active()
        self.model_selected.emit(model_id)

    def _delete_model(self, model_id: str) -> None:
        """Confirm + remove the on-disk cache for ``model_id``.

        Refuses to delete the active model (the row already disables the
        button, but we double-check here so an external caller can't slip
        through). Failures are logged but never raised — the user gets a
        message-box instead so the page stays usable.
        """
        if model_id == self._active_model_id:
            return
        row = self._rows.get(model_id)
        if row is None or not row.model.is_downloaded(self._download_root):
            return
        if not _confirm_delete(self, row.model.label):
            return
        try:
            _delete_model_files(row.model.cache_path(self._download_root))
        except OSError as exc:
            _log.warning("failed to delete %s: %s", model_id, exc)
            QMessageBox.warning(
                self, "Delete failed",
                f"Could not remove the model files: {exc}",
            )
            return
        row.refresh_download_state()

    def _refresh_active(self) -> None:
        for mid, row in self._rows.items():
            row.set_active(mid == self._active_model_id)

    def _start_download(self, model_id: str) -> None:
        if model_id in self._workers:
            return
        row = self._rows.get(model_id)
        if row is None:
            return
        row.set_downloading(True)

        thread = QThread(self)
        worker = _DownloadWorker(model_id, self._download_root)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_download_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._workers[model_id] = (thread, worker)
        thread.start()
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def _on_download_finished(self, model_id: str, ok: bool, error: str) -> None:
        row = self._rows.get(model_id)
        if row is not None:
            row.set_downloading(False)
            row.refresh_download_state()
        self._workers.pop(model_id, None)
        if not self._workers:
            self._poll_timer.stop()
        if not ok:
            _log.warning("download of %s failed: %s", model_id, error)

    def _poll_progress(self) -> None:
        """Walk each downloading model's cache dir and update its bar.

        Coarse but useful: faster-whisper / huggingface_hub doesn't surface
        a per-byte callback, but the on-disk size grows monotonically as
        the model is fetched, so size_on_disk / advertised_size_mb is a
        decent proxy. We clamp to 99% so the bar never claims completion
        before the worker thread actually finishes.
        """
        for model_id in list(self._workers.keys()):
            row = self._rows.get(model_id)
            if row is None or row.model.size_mb <= 0:
                continue
            target = row.model.size_mb * 1024 * 1024
            current = _dir_size_bytes(row.model.cache_path(self._download_root))
            if current <= 0:
                continue
            row.set_progress(current / target)


# ---- Cloud panel --------------------------------------------------------------

class _CloudPanel(QWidget):
    """API-key entry + model dropdown for one cloud provider."""

    config_dirty = Signal()  # emit when any field changes so window saves

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._provider: CloudProvider | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        cloud_card = card()
        layout = QFormLayout(cloud_card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(10)

        self._rate_label = QLabel()
        self._rate_label.setProperty("hint", True)

        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(lambda _: self.config_dirty.emit())

        # Direct API-key entry, password-masked. The key writes to the
        # OS keychain via secrets.set() on save — never to config.toml,
        # never to the user's environment. Empty field = "leave the
        # currently stored key alone" so re-saving an unrelated change
        # (e.g. switching the model) doesn't clobber a key that was
        # set in a previous session.
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Paste your API key")
        self.api_key_input.editingFinished.connect(self.config_dirty.emit)

        layout.addRow("Pricing:", self._rate_label)
        layout.addRow("Model:", self.model_combo)
        layout.addRow("API key:", self.api_key_input)

        self._key_status = QLabel()
        self._key_status.setProperty("hint", True)
        self._key_status.setWordWrap(True)
        layout.addRow("", self._key_status)

        # Test-connection row: button + status label. Sends a 1-second
        # silence clip to the endpoint so the user can validate the
        # key + base URL combination before discovering the breakage
        # on a real push-to-talk press.
        self._test_btn = primary_button("Test connection")
        self._test_btn.clicked.connect(self._on_test_clicked)
        self._test_status = QLabel()
        self._test_status.setProperty("hint", True)
        self._test_status.setWordWrap(True)
        layout.addRow(self._test_btn, self._test_status)

        outer.addWidget(cloud_card)
        outer.addStretch(1)

        self.api_key_input.textChanged.connect(self._refresh_key_status)
        self._test_thread: QThread | None = None
        self._test_worker: _ProbeWorker | None = None

    def set_provider(self, provider: CloudProvider, cfg: config_mod.Config) -> None:
        self._provider = provider
        self._rate_label.setText(provider.rate_hint or "—")

        # Detect "switching providers" vs "showing the saved one":
        # honoring saved model/api_key_env across a provider switch was
        # the bug — selecting Groq still left the env-var field on
        # ``OPENAI_API_KEY`` because that was the persisted value
        # from the previous (OpenAI) session.
        is_active_provider = cfg.cloud_provider_id == provider.id

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(provider.models)
        if is_active_provider and cfg.openai.model in provider.models:
            self.model_combo.setCurrentText(cfg.openai.model)
        else:
            self.model_combo.setCurrentText(provider.default_model)
        self.model_combo.blockSignals(False)

        # Field starts empty per provider so users can type a fresh key
        # without seeing a stale one from another provider. The status
        # line below shows whether a key is already stored for this
        # provider (keychain or env var).
        self.api_key_input.blockSignals(True)
        self.api_key_input.clear()
        self.api_key_input.blockSignals(False)
        self._refresh_key_status()

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        if self._provider is None:
            return cfg
        # Persist the user-typed key to the OS keychain. Empty field
        # means "no change" — we don't want a model-only edit to wipe
        # a previously-saved key.
        typed = self.api_key_input.text().strip()
        if typed:
            try:
                secrets.set(self._provider.id, typed)
            except Exception as e:  # noqa: BLE001
                _log.warning("failed to write %s key to keychain: %s",
                             self._provider.id, e)
            # Clear the visible value once it's been stored so the
            # next session can't read it back from the field.
            self.api_key_input.blockSignals(True)
            self.api_key_input.clear()
            self.api_key_input.blockSignals(False)
        # Keep the env-var name pinned to the provider's default so
        # the env-var fallback in secrets.get() works for users who
        # set the key via direnv / 1Password CLI / shell rc instead
        # of the keychain.
        cfg.openai.api_key_env = self._provider.api_key_env
        cfg.openai.model = self.model_combo.currentText() or self._provider.default_model
        return cfg

    def _refresh_key_status(self) -> None:
        if self._provider is None:
            self._key_status.setText("")
            return
        # secrets.get() checks keychain first, env var second — the
        # status line tells the user which path is currently providing
        # the key, or that none is configured.
        try:
            from .. import secrets as secrets_mod
            stored = secrets_mod.get(
                self._provider.id, env_var=self._provider.api_key_env,
            )
        except Exception:  # noqa: BLE001
            stored = None
        if stored:
            in_keychain = False
            try:
                import keyring
                in_keychain = bool(keyring.get_password("murmur", self._provider.id))
            except Exception:  # noqa: BLE001
                pass
            source = "keychain" if in_keychain else f"{self._provider.api_key_env} env var"
            self._key_status.setText(f"✓ Key is set ({source}).")
        else:
            self._key_status.setText(
                "⚠ No API key configured. Paste your key above and save."
            )

    # -- Test connection --------------------------------------------------

    def _on_test_clicked(self) -> None:
        """Spin up a background probe so the UI stays responsive.

        ``probe_connection`` does a real network round-trip to the
        provider's transcription endpoint with a 1-second silence
        clip — running on the UI thread would freeze the window for
        500ms-2s on the happy path and longer on timeouts. The worker
        emits its result via Qt signal, which we render in
        ``_on_test_result``.
        """
        if self._provider is None or self._test_thread is not None:
            return
        # If the user has typed a fresh key in the field, test that
        # one — useful for verifying a key before committing it to
        # the keychain. Otherwise fall through to the stored key
        # (keychain or env-var fallback).
        typed = self.api_key_input.text().strip()
        api_key = typed or (
            secrets.get(self._provider.id, env_var=self._provider.api_key_env) or ""
        )
        model = self.model_combo.currentText() or self._provider.default_model
        self._test_btn.setEnabled(False)
        self._test_status.setText("Pinging…")

        self._test_thread = QThread(self)
        self._test_worker = _ProbeWorker(
            base_url=self._provider.base_url or "https://api.openai.com/v1",
            api_key=api_key,
            model=model,
        )
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self._on_test_result)
        self._test_worker.finished.connect(self._test_thread.quit)
        self._test_worker.finished.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread.deleteLater)
        self._test_thread.start()

    def _on_test_result(self, ok: bool, message: str) -> None:
        prefix = "✓ " if ok else "⚠ "
        self._test_status.setText(prefix + message)
        self._test_btn.setEnabled(True)
        self._test_thread = None
        self._test_worker = None


class _ProbeWorker(QObject):
    """Threaded wrapper around :func:`probe_connection`.

    Lives long enough to emit one ``finished(ok, message)`` signal,
    then deletes itself. The Cloud panel keeps a reference until the
    signal fires so Qt doesn't garbage-collect it mid-call.
    """

    finished = Signal(bool, str)

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def run(self) -> None:
        from ..transcribe.openai_compatible import probe_connection
        ok, message = probe_connection(self.base_url, self.api_key, self.model)
        self.finished.emit(ok, message)


# ---- The page itself ----------------------------------------------------------

class ModelsPage(QWidget):
    """Top-level provider picker + Local/Cloud detail panels."""

    preferences_changed = Signal()

    LOCAL_PROVIDER_ID = "local"

    def __init__(self, cfg: config_mod.Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        layout.addWidget(section_label("Provider"))
        provider_card = card()
        provider_form = QFormLayout(provider_card)
        provider_form.setContentsMargins(18, 14, 18, 14)
        provider_form.setHorizontalSpacing(16)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Local (on-device)", userData=self.LOCAL_PROVIDER_ID)
        for provider in providers_mod.list_cloud():
            self.provider_combo.addItem(provider.label, userData=provider.id)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_form.addRow("Provider:", self.provider_combo)
        layout.addWidget(provider_card)
        layout.addWidget(section_label("Models"))

        self._stack = QStackedWidget()
        self._local_panel = _LocalPanel(cfg)
        self._cloud_panel = _CloudPanel()
        self._stack.addWidget(self._local_panel)
        self._stack.addWidget(self._cloud_panel)
        layout.addWidget(self._stack, 1)

        # Wire children's change signals into the page-level one.
        self._local_panel.model_selected.connect(lambda _: self.preferences_changed.emit())
        self._cloud_panel.config_dirty.connect(self.preferences_changed.emit)

        self._select_provider_in_ui(cfg)

    # ------------------------------------------------------------------

    def set_config(self, cfg: config_mod.Config) -> None:
        self._cfg = cfg
        self._local_panel.set_config(cfg)
        self._select_provider_in_ui(cfg)

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        provider_id = self.provider_combo.currentData()
        if provider_id == self.LOCAL_PROVIDER_ID:
            cfg.backend = "local"
            cfg.local.model = self._local_panel.active_model_id
        else:
            cfg.backend = "cloud"
            cfg.cloud_provider_id = provider_id
            cfg = self._cloud_panel.apply_to_config(cfg)
        return cfg

    # ------------------------------------------------------------------

    def _on_provider_changed(self, _idx: int) -> None:
        self._sync_stack()
        self.preferences_changed.emit()

    def _select_provider_in_ui(self, cfg: config_mod.Config) -> None:
        # Translate the (backend, cloud_provider_id) pair into a single
        # dropdown id: local stays "local"; cloud uses the provider id.
        # Unknown backend strings (e.g. a hand-edited TOML pointing at a
        # provider that's no longer registered) fall through to local
        # rather than silently picking a wrong cloud row — same shape
        # the pre-#17 code had for unknown providers.
        if cfg.backend == "local":
            target = self.LOCAL_PROVIDER_ID
        elif cfg.backend == "cloud":
            target = cfg.cloud_provider_id
        else:
            target = None
        # Rebuild the dropdown selection without firing changed signals.
        self.provider_combo.blockSignals(True)
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemData(i) == target:
                self.provider_combo.setCurrentIndex(i)
                break
        else:
            # Backend in TOML doesn't match any registered provider —
            # fall back to local rather than ignoring the user's pick.
            self.provider_combo.setCurrentIndex(0)
        self.provider_combo.blockSignals(False)
        self._sync_stack()

    def _sync_stack(self) -> None:
        provider_id = self.provider_combo.currentData()
        if provider_id == self.LOCAL_PROVIDER_ID:
            self._stack.setCurrentWidget(self._local_panel)
            return
        provider = providers_mod.get_cloud(provider_id)
        if provider is None:
            self._stack.setCurrentWidget(self._local_panel)
            return
        self._cloud_panel.set_provider(provider, self._cfg)
        self._stack.setCurrentWidget(self._cloud_panel)


# ---- Helpers ------------------------------------------------------------------

def _qt_right_center():
    """Right-aligned, vertically-centered. Lazy import keeps offscreen
    Qt happy on test machines that don't import QtCore eagerly."""
    from PySide6.QtCore import Qt
    return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _format_size(mb: int) -> str:
    if mb <= 0:
        return "—"
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb} MB"


def _dir_size_bytes(path: Path) -> int:
    """Total size of every regular file under ``path``, recursively.

    Used to estimate download progress against a model's advertised
    size. Returns 0 if the directory doesn't exist yet (download
    hasn't started writing anything).
    """
    import contextlib

    if not path.exists():
        return 0
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                with contextlib.suppress(OSError):
                    total += p.stat().st_size
    except OSError:
        return total
    return total


def _confirm_delete(parent: QWidget, label: str) -> bool:
    """Modal yes/no dialog before nuking model files. Patchable in tests."""
    reply = QMessageBox.question(
        parent,
        "Delete model?",
        f"Remove the {label} model from disk? You can re-download it later.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return reply == QMessageBox.StandardButton.Yes


def _delete_model_files(path: Path) -> None:
    """Recursively remove ``path`` if it exists. Raises OSError on failure."""
    if path.exists():
        shutil.rmtree(path)


__all__ = ["ModelsPage", "find_local_model"]
