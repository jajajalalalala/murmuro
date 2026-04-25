from murmur import config as config_mod


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "config_path", lambda: tmp_path / "config.toml")
    cfg = config_mod.load()
    assert cfg.backend == "local"
    cfg.backend = "openai"
    cfg.language = "en"
    config_mod.save(cfg)
    cfg2 = config_mod.load()
    assert cfg2.backend == "openai"
    assert cfg2.language == "en"
