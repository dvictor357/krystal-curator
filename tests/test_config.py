from krystal_curator.config import Config, load, write_templates


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KRYSTAL_CONFIG", raising=False)
    for k in ("KRYSTAL_SIZE", "KRYSTAL_PROFILE", "KRYSTAL_WALLET"):
        monkeypatch.delenv(k, raising=False)
    cfg = load()
    assert cfg.source is None and cfg.chain == 4663 and cfg.profile == "balanced"
    assert cfg.quote_or_none == "USDG"
    assert Config(quote="any").quote_or_none is None


def test_file_then_env_precedence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        'profile = "degen"\nsize = 1234\nprotocols = ["ramsescl"]\n'
        "digest_hour = 3\n[alerts]\nedge_sigma = 0.8\n"
    )
    monkeypatch.delenv("KRYSTAL_SIZE", raising=False)
    cfg = load()
    assert cfg.source == tmp_path / "config.toml"
    assert cfg.profile == "degen" and cfg.size == 1234 and cfg.protocols == ["ramsescl"]
    assert cfg.digest_hour == 3 and cfg.alerts.edge_sigma == 0.8
    monkeypatch.setenv("KRYSTAL_SIZE", "999")
    monkeypatch.setenv("KRYSTAL_TELEGRAM", "yes")
    cfg = load()
    assert cfg.size == 999 and cfg.telegram is True


def test_templates_parse_and_do_not_overwrite(tmp_path, monkeypatch):
    made = write_templates(tmp_path)
    assert {p.name for p in made} == {"config.toml", ".env"}
    monkeypatch.chdir(tmp_path)
    cfg = load()
    assert cfg.source == tmp_path / "config.toml" and cfg.size == 50_000
    assert write_templates(tmp_path) == []
