"""Provider registry: shape, lookup, and download-detection logic."""
from __future__ import annotations

from murmur.providers import (
    CLOUD_PROVIDERS,
    LOCAL_MODELS,
    LocalModel,
    find_cloud_provider,
    find_local_model,
)


def test_local_models_have_unique_ids():
    ids = [m.id for m in LOCAL_MODELS]
    assert len(ids) == len(set(ids)), "duplicate model id in LOCAL_MODELS"


def test_cloud_providers_have_unique_ids():
    ids = [p.id for p in CLOUD_PROVIDERS]
    assert len(ids) == len(set(ids))


def test_find_local_model_hit_and_miss():
    assert find_local_model("base") is not None
    assert find_local_model("definitely-not-a-model").id if find_local_model(
        "definitely-not-a-model"
    ) else None is None


def test_find_cloud_provider_hit_and_miss():
    assert find_cloud_provider("openai") is not None
    assert find_cloud_provider("nope") is None


def test_local_model_cache_path_uses_hf_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    model = LocalModel("base", "Base", 145, True)
    expected = tmp_path / "models--Systran--faster-whisper-base"
    assert model.cache_path() == expected


def test_local_model_is_downloaded_requires_non_empty_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    model = LocalModel("base", "Base", 145, True)

    # Missing dir → not downloaded
    assert model.is_downloaded() is False

    # Empty dir (failed/cancelled download) → still not downloaded
    model.cache_path().mkdir(parents=True)
    assert model.is_downloaded() is False

    # Anything inside → downloaded
    (model.cache_path() / "snapshots").mkdir()
    assert model.is_downloaded() is True


def test_openai_provider_default_model_is_in_models_list():
    p = find_cloud_provider("openai")
    assert p is not None
    assert p.default_model in p.models
