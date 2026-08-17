"""Agent config store: defaults, round-trip, atomicity, blocklist matching."""

from agentconfig import store


def test_defaults_when_missing(data_dir):
    cfg = store.load()
    assert cfg.enabled is True
    assert cfg.blocked_companies == []
    assert cfg.run_at == ["09:00", "15:00"]
    assert cfg.run_days == ["mon", "tue", "wed", "thu", "fri"]


def test_round_trip(data_dir):
    cfg = store.load()
    cfg.enabled = False
    cfg.blocked_companies = ["Acme GmbH"]
    cfg.run_at = ["07:30"]
    cfg.run_days = ["sat", "sun"]
    store.save(cfg)
    again = store.load()
    assert again == cfg
    assert (data_dir / "agent_config.json").exists()


def test_corrupt_file_yields_defaults(data_dir):
    (data_dir / "agent_config.json").write_text("not json", encoding="utf-8")
    assert store.load() == store.AgentConfig()


def test_partial_file_keeps_defaults_for_missing_fields(data_dir):
    (data_dir / "agent_config.json").write_text('{"enabled": false}', encoding="utf-8")
    cfg = store.load()
    assert cfg.enabled is False
    assert cfg.run_at == ["09:00", "15:00"]


def test_is_blocked_matches_like_cooldown(data_dir):
    cfg = store.AgentConfig(blocked_companies=["  Acme GmbH "])
    assert store.is_blocked(cfg, "acme gmbh")
    assert store.is_blocked(cfg, "ACME GMBH  ")
    assert not store.is_blocked(cfg, "Acme")          # exact equality, not substring
    assert not store.is_blocked(cfg, "")
    assert not store.is_blocked(cfg, None)  # type: ignore[arg-type]


def test_from_dict_rejects_non_string_list_elements_blocked_companies(data_dir):
    cfg = store.AgentConfig.from_dict({"blocked_companies": [1, 2, 3]})
    assert cfg.blocked_companies == []


def test_from_dict_rejects_non_string_list_elements_run_at(data_dir):
    cfg = store.AgentConfig.from_dict({"run_at": [1, 2, 3]})
    assert cfg.run_at == ["09:00", "15:00"]


def test_from_dict_rejects_non_string_list_elements_run_days(data_dir):
    cfg = store.AgentConfig.from_dict({"run_days": ["mon", 1, "tue"]})
    assert cfg.run_days == ["mon", "tue", "wed", "thu", "fri"]


def test_is_blocked_never_raises_on_malformed_config(data_dir):
    (data_dir / "agent_config.json").write_text(
        '{"blocked_companies": [1, 2, 3]}', encoding="utf-8"
    )
    cfg = store.load()
    # Should not raise AttributeError, should return False for any company
    assert not store.is_blocked(cfg, "acme")
    assert not store.is_blocked(cfg, "")
