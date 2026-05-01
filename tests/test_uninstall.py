"""``murmuro --uninstall`` removes config, logs, and the private model store.

The test redirects every path the uninstaller looks at into a tmp dir
so the user's real ``~/Library/Application Support/Murmuro`` is never
at risk during CI or local pytest runs. The legacy HuggingFace cache
(``~/.cache/huggingface/hub/``) is also pinned to a tmp location and
asserted to be untouched — Murmuro stopped managing it in #12 and the
uninstall flow must respect that.
"""
from __future__ import annotations

import io
from pathlib import Path

from murmuro import uninstall


def _seed(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    """Lay down the dirs an uninstall would target. Returns the map of
    role → path so individual tests can assert on each one."""
    config_dir = tmp_path / "config"
    log_dir = tmp_path / "logs"
    # New private model store under platformdirs.user_data_dir.
    model_store = tmp_path / "data" / "Murmuro" / "models"
    # Legacy HF cache — must NOT be touched by uninstall.
    hf_root = tmp_path / "hf"

    config_dir.mkdir()
    (config_dir / "config.toml").write_text("backend='local'\n")
    log_dir.mkdir()
    (log_dir / "murmuro.log").write_text("hello\n")
    model_store.mkdir(parents=True)
    (model_store / "models--Systran--faster-whisper-base").mkdir()
    (model_store / "models--Systran--faster-whisper-base" / "weights.bin").write_bytes(
        b"x" * 16
    )
    hf_root.mkdir()
    legacy = hf_root / "models--Systran--faster-whisper-base"
    legacy.mkdir()
    (legacy / "weights.bin").write_bytes(b"y" * 16)

    from murmuro import _logging as logmod
    from murmuro import config as cfgmod
    monkeypatch.setattr(cfgmod, "config_path", lambda: config_dir / "config.toml")
    monkeypatch.setattr(logmod, "log_path", lambda: log_dir / "murmuro.log")
    monkeypatch.setattr(uninstall, "_model_store_root", lambda: model_store)
    # Pin HOME so the printed legacy hint is correct and any accidental
    # rmtree against the real ~/.cache/huggingface is impossible.
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    return {
        "config": config_dir,
        "log": log_dir,
        "model_store": model_store,
        "legacy_hf_cache": legacy,
    }


def test_collect_targets_finds_config_logs_and_model_store(tmp_path, monkeypatch):
    paths = _seed(tmp_path, monkeypatch)
    targets = uninstall.collect_targets()
    found = {t.path for t in targets}
    assert paths["config"] in found
    assert paths["log"] in found
    assert paths["model_store"] in found


def test_collect_targets_does_not_include_legacy_hf_cache(tmp_path, monkeypatch):
    """The HF cache is explicitly out of scope after #12."""
    paths = _seed(tmp_path, monkeypatch)
    target_paths = {t.path for t in uninstall.collect_targets()}
    assert paths["legacy_hf_cache"] not in target_paths


def test_run_with_yes_removes_only_private_paths(tmp_path, monkeypatch):
    """--yes removes config / logs / model store and leaves the HF
    cache untouched (orphan policy from issue #12)."""
    paths = _seed(tmp_path, monkeypatch)
    out = io.StringIO()
    rc = uninstall.run(assume_yes=True, out=out)
    assert rc == 0
    assert not paths["config"].exists()
    assert not paths["log"].exists()
    assert not paths["model_store"].exists()
    # Legacy HF cache survived the uninstall.
    assert paths["legacy_hf_cache"].exists()


def test_run_prints_orphan_hint_in_dry_run(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    out = io.StringIO()
    rc = uninstall.run(assume_yes=True, dry_run=True, out=out)
    assert rc == 0
    text = out.getvalue()
    assert "~/.cache/huggingface/hub/" in text
    assert "models--Systran--faster-whisper-*" in text


def test_run_prints_orphan_hint_in_real_run(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    out = io.StringIO()
    uninstall.run(assume_yes=True, out=out)
    text = out.getvalue()
    assert "~/.cache/huggingface/hub/" in text


def test_run_prints_new_model_store_path_not_legacy(tmp_path, monkeypatch):
    """The plan listing should reference the private store, not the HF cache."""
    paths = _seed(tmp_path, monkeypatch)
    out = io.StringIO()
    uninstall.run(assume_yes=True, dry_run=True, out=out)
    text = out.getvalue()
    assert str(paths["model_store"]) in text
    # The line "Model store: ..." should not point at the legacy cache.
    assert str(paths["legacy_hf_cache"]) not in text.split("Manual cleanup")[0]


def test_dry_run_changes_nothing(tmp_path, monkeypatch):
    paths = _seed(tmp_path, monkeypatch)
    out = io.StringIO()
    rc = uninstall.run(assume_yes=True, dry_run=True, out=out)
    assert rc == 0
    for key in ("config", "log", "model_store", "legacy_hf_cache"):
        assert paths[key].exists(), f"{key} was removed during --dry-run"
    assert "dry-run" in out.getvalue().lower()


def test_run_aborts_on_negative_confirmation(tmp_path, monkeypatch):
    """Pressing 'n' bails before any rmtree."""
    paths = _seed(tmp_path, monkeypatch)
    out = io.StringIO()
    rc = uninstall.run(assume_yes=False, confirm=lambda _p: False, out=out)
    assert rc == 1
    assert paths["config"].exists()
    assert paths["model_store"].exists()


def test_run_with_no_state_returns_zero(tmp_path, monkeypatch):
    """Running on a clean machine is a no-op success."""
    from murmuro import _logging as logmod
    from murmuro import config as cfgmod
    monkeypatch.setattr(cfgmod, "config_path", lambda: tmp_path / "missing/config.toml")
    monkeypatch.setattr(logmod, "log_path", lambda: tmp_path / "missing/log/murmuro.log")
    monkeypatch.setattr(
        uninstall, "_model_store_root", lambda: tmp_path / "missing/data",
    )
    out = io.StringIO()
    rc = uninstall.run(assume_yes=True, out=out)
    assert rc == 0
    assert "no Murmuro state" in out.getvalue()
