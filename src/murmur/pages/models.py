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

import os
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
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config as config_mod
from .._logging import get_logger
from ..providers import (
    CLOUD_PROVIDERS,
    LOCAL_MODELS,
    CloudProvider,
    LocalModel,
    find_cloud_provider,
    find_local_model,
)
from ..ui.theme import card, primary_button, section_label

_log = get_logger("models_page")


# ---- Worker for blocking faster-whisper downloads -----------------------------

class _DownloadWorker(QObject):
    """Materialize a faster-whisper model in its own thread.

    Instantiating ``WhisperModel(name)`` triggers the HuggingFace download
    if the model isn't cached. The constructor is blocking and noisy, so
    we run it off the UI thread and let the UI listen for ``finished``.
    """

    finished = Signal(str, bool, str)  # (model_id, ok, error_message)

    def __init__(self, model_id: str) -> None:
        super().__init__()
        self.model_id = model_id

    def run(self) -> None:
        try:
            from faster_whisper import WhisperModel

            # device=cpu, compute_type=int8 is the cheapest "just download"
            # combo that works on every machine. Real transcription uses
            # the user's chosen device/compute_type from cfg.local.
            WhisperModel(self.model_id, device="cpu", compute_type="int8")
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

    def __init__(self, model: LocalModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model
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

        self._status = QLabel()
        self._status.setProperty("hint", True)

        # Inline progress bar — hidden until a download is in flight.
        # Width is bounded so the row keeps its existing proportions when
        # the bar appears in place of the status label.
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFixedWidth(160)
        self._progress.setVisible(False)

        self._action = primary_button("")
        self._action.clicked.connect(self._on_action)

        # Secondary "Delete" button: removes the on-disk model files.
        # Hidden until the model is downloaded; disabled while it's the
        # active backend (would yank the rug from under a running app).
        self._delete = QPushButton("Delete")
        self._delete.clicked.connect(self._on_delete)
        self._delete.setVisible(False)

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
        if self.model.is_downloaded():
            self.use_requested.emit(self.model.id)
        else:
            self.download_requested.emit(self.model.id)

    def _on_delete(self) -> None:
        if self._is_downloading or self._is_active:
            return
        if not self.model.is_downloaded():
            return
        self.delete_requested.emit(self.model.id)

    def _refresh(self) -> None:
        downloaded = self.model.is_downloaded()
        if self._is_downloading:
            self._action.setEnabled(False)
            self._action.setText("Downloading…")
            self._delete.setVisible(False)
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
            self._delete.setVisible(False)
            return
        # Downloaded — Delete is visible. It's only disabled for the
        # currently-active model so the user can't yank it from under
        # a live transcribe call; switching to another model re-enables.
        self._delete.setVisible(True)
        if self._is_active:
            self._action.setText("In use")
            self._action.setEnabled(False)
            self._status.setText("Active")
            self._delete.setEnabled(False)
            self._delete.setToolTip(
                "Switch to another model first, then delete this one."
            )
        else:
            self._action.setText("Use")
            self._status.setText("Downloaded")
            self._delete.setEnabled(True)
            self._delete.setToolTip("")


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

        # Single timer drives every in-flight progress bar — faster-whisper's
        # constructor is opaque, so we estimate progress by polling the size
        # of the HuggingFace cache directory against the model's known total.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_progress)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        for model in LOCAL_MODELS:
            row = _LocalModelRow(model)
            row.download_requested.connect(self._start_download)
            row.use_requested.connect(self._select_model)
            row.delete_requested.connect(self._delete_model)
            layout.addWidget(row)
            self._rows[model.id] = row

        # Custom-model rows aren't shipped in the registry but the user may
        # have entered one in the TOML by hand — keep it visible/active.
        if cfg.local.model not in self._rows:
            custom = LocalModel(
                id=cfg.local.model,
                label=cfg.local.model + " (custom)",
                size_mb=0,
                multilingual=True,
            )
            row = _LocalModelRow(custom)
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
        if row is None or not row.model.is_downloaded():
            return
        if not _confirm_delete(self, row.model.label):
            return
        try:
            _delete_model_files(row.model.cache_path())
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
        worker = _DownloadWorker(model_id)
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
            current = _dir_size_bytes(row.model.cache_path())
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

        self.api_key_env = QLineEdit()
        self.api_key_env.editingFinished.connect(self.config_dirty.emit)

        layout.addRow("Pricing:", self._rate_label)
        layout.addRow("Model:", self.model_combo)
        layout.addRow("API key env var:", self.api_key_env)

        self._key_status = QLabel()
        self._key_status.setProperty("hint", True)
        layout.addRow("", self._key_status)
        outer.addWidget(cloud_card)
        outer.addStretch(1)

        self.api_key_env.textChanged.connect(self._refresh_key_status)

    def set_provider(self, provider: CloudProvider, cfg: config_mod.Config) -> None:
        self._provider = provider
        self._rate_label.setText(provider.rate_hint or "—")
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(provider.models)
        # Honor the user's previously-saved model if it lives in this
        # provider's list; otherwise fall back to the provider default.
        if cfg.openai.model in provider.models:
            self.model_combo.setCurrentText(cfg.openai.model)
        else:
            self.model_combo.setCurrentText(provider.default_model)
        self.model_combo.blockSignals(False)

        self.api_key_env.blockSignals(True)
        self.api_key_env.setText(cfg.openai.api_key_env or provider.api_key_env)
        self.api_key_env.blockSignals(False)
        self._refresh_key_status()

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        if self._provider is None:
            return cfg
        cfg.openai.api_key_env = (
            self.api_key_env.text().strip() or self._provider.api_key_env
        )
        cfg.openai.model = self.model_combo.currentText() or self._provider.default_model
        return cfg

    def _refresh_key_status(self) -> None:
        env = self.api_key_env.text().strip()
        if not env:
            self._key_status.setText("Enter the env var that holds your API key.")
            return
        if os.environ.get(env):
            self._key_status.setText(f"✓ {env} is set in this session.")
        else:
            self._key_status.setText(
                f"⚠ {env} not set in this session. Export it before using this backend."
            )


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
        for provider in CLOUD_PROVIDERS:
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

        self._select_provider_in_ui(cfg.backend)

    # ------------------------------------------------------------------

    def set_config(self, cfg: config_mod.Config) -> None:
        self._cfg = cfg
        self._local_panel.set_config(cfg)
        self._select_provider_in_ui(cfg.backend)

    def apply_to_config(self, cfg: config_mod.Config) -> config_mod.Config:
        provider_id = self.provider_combo.currentData()
        if provider_id == self.LOCAL_PROVIDER_ID:
            cfg.backend = "local"
            cfg.local.model = self._local_panel.active_model_id
        else:
            cfg.backend = provider_id
            cfg = self._cloud_panel.apply_to_config(cfg)
        return cfg

    # ------------------------------------------------------------------

    def _on_provider_changed(self, _idx: int) -> None:
        self._sync_stack()
        self.preferences_changed.emit()

    def _select_provider_in_ui(self, backend: str) -> None:
        # Rebuild the dropdown selection without firing changed signals.
        self.provider_combo.blockSignals(True)
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemData(i) == backend:
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
        provider = find_cloud_provider(provider_id)
        if provider is None:
            self._stack.setCurrentWidget(self._local_panel)
            return
        self._cloud_panel.set_provider(provider, self._cfg)
        self._stack.setCurrentWidget(self._cloud_panel)


# ---- Helpers ------------------------------------------------------------------

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
