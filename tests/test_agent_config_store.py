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
    cfg.mode = "off"
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
    # Identity-key match: a legal-entity suffix does not let a blocked
    # company slip through under a shorter spelling of the same name.
    assert store.is_blocked(cfg, "Acme")
    assert not store.is_blocked(cfg, "")
    assert not store.is_blocked(cfg, None)  # type: ignore[arg-type]


def test_is_blocked_suffix_equivalence_both_directions(data_dir):
    """A legal-entity suffix on either the blocklist or the incoming name matches."""
    bare = store.AgentConfig(blocked_companies=["RobCo"])
    assert store.is_blocked(bare, "RobCo GmbH")
    assert store.is_blocked(bare, "robco gmbh.")

    suffixed = store.AgentConfig(blocked_companies=["RobCo GmbH"])
    assert store.is_blocked(suffixed, "RobCo")
    assert store.is_blocked(suffixed, "ROBCO")

    # An unrelated company is still not blocked.
    assert not store.is_blocked(bare, "Initech")


def test_is_blocked_blank_and_non_str_still_false(data_dir):
    cfg = store.AgentConfig(blocked_companies=["RobCo"])
    assert not store.is_blocked(cfg, "")
    assert not store.is_blocked(cfg, "   ")
    assert not store.is_blocked(cfg, None)  # type: ignore[arg-type]
    assert not store.is_blocked(cfg, 12345)  # type: ignore[arg-type]


def test_from_dict_rejects_non_string_list_elements_blocked_companies(data_dir):
    cfg = store.AgentConfig.from_dict({"blocked_companies": [1, 2, 3]})
    assert cfg.blocked_companies == []


def test_from_dict_rejects_non_string_list_elements_run_at(data_dir):
    cfg = store.AgentConfig.from_dict({"run_at": [1, 2, 3]})
    assert cfg.run_at == ["09:00", "15:00"]


def test_from_dict_rejects_non_string_list_elements_run_days(data_dir):
    cfg = store.AgentConfig.from_dict({"run_days": ["mon", 1, "tue"]})
    assert cfg.run_days == ["mon", "tue", "wed", "thu", "fri"]


def test_run_timezone_defaults_to_utc(data_dir):
    """A fresh config carries UTC until the operator picks a zone."""
    assert store.AgentConfig().run_timezone == "UTC"


def test_run_timezone_round_trip(data_dir):
    cfg = store.AgentConfig()
    cfg.run_timezone = "Europe/Berlin"
    store.save(cfg)
    again = store.load()
    assert again.run_timezone == "Europe/Berlin"


def test_from_dict_unknown_zone_falls_back_to_utc(data_dir):
    """A garbage zone string that zoneinfo cannot resolve degrades to UTC."""
    cfg = store.AgentConfig.from_dict({"run_timezone": "Mars/Olympus"})
    assert cfg.run_timezone == "UTC"


def test_from_dict_non_string_zone_falls_back_to_utc(data_dir):
    """A non-string or empty run_timezone degrades to UTC, never raises."""
    assert store.AgentConfig.from_dict({"run_timezone": 123}).run_timezone == "UTC"
    assert store.AgentConfig.from_dict({"run_timezone": ""}).run_timezone == "UTC"


def test_config_predating_run_timezone_loads_as_utc(data_dir):
    """A config file written before the field existed migrates to UTC."""
    (data_dir / "agent_config.json").write_text(
        '{"run_at": ["09:00"], "run_days": ["mon"]}', encoding="utf-8"
    )
    cfg = store.load()
    assert cfg.run_timezone == "UTC"


def test_to_dict_emits_run_timezone(data_dir):
    assert "run_timezone" in store.AgentConfig().to_dict()


def test_is_blocked_never_raises_on_malformed_config(data_dir):
    (data_dir / "agent_config.json").write_text(
        '{"blocked_companies": [1, 2, 3]}', encoding="utf-8"
    )
    cfg = store.load()
    # Should not raise AttributeError, should return False for any company
    assert not store.is_blocked(cfg, "acme")
    assert not store.is_blocked(cfg, "")


def test_profiles_round_trip(data_dir):
    cfg = store.AgentConfig()
    cfg.profiles = [
        store.JobProfile(
            name="Senior Python",
            enabled=True,
            keywords=["Python", "FastAPI"],
            locations=["Berlin", "Remote"],
            salary_floor=90000,
            salary_ask_min=100000,
            salary_ask_max=130000,
        )
    ]
    cfg.target_companies = ["Google", "Acme GmbH"]
    cfg.cooldown_days = 30
    cfg.max_applications_per_run = 5
    store.save(cfg)
    again = store.load()
    assert len(again.profiles) == 1
    assert again.profiles[0].name == "Senior Python"
    assert again.profiles[0].keywords == ["Python", "FastAPI"]
    assert again.profiles[0].salary_floor == 90000
    assert again.target_companies == ["Google", "Acme GmbH"]
    assert again.cooldown_days == 30
    assert again.max_applications_per_run == 5


def test_empty_profiles_list(data_dir):
    cfg = store.AgentConfig()
    cfg.profiles = []
    store.save(cfg)
    again = store.load()
    assert again.profiles == []


def test_profile_with_wrong_type_field_falls_back_to_default(data_dir):
    (data_dir / "agent_config.json").write_text(
        """{
            "profiles": [
                {
                    "name": "Test",
                    "enabled": "not a bool",
                    "keywords": 123,
                    "salary_floor": "not an int"
                }
            ]
        }""",
        encoding="utf-8",
    )
    cfg = store.load()
    assert len(cfg.profiles) == 1
    assert cfg.profiles[0].name == "Test"
    assert cfg.profiles[0].enabled is True  # falls back to default
    assert cfg.profiles[0].keywords == []  # falls back to default
    assert cfg.profiles[0].salary_floor is None  # falls back to default


def test_unknown_top_level_key_ignored(data_dir):
    (data_dir / "agent_config.json").write_text(
        '{"enabled": true, "unknown_field": "value"}',
        encoding="utf-8",
    )
    cfg = store.load()
    assert cfg.enabled is True
    assert not hasattr(cfg, "unknown_field")


# --- Per-window cooldown fields -------------------------------------------


def test_cooldown_windows_round_trip(data_dir):
    """Both new cooldown windows survive from_dict -> to_dict -> disk."""
    cfg = store.AgentConfig(cooldown_days_same_role=90, cooldown_days_same_company=30)
    restored = store.AgentConfig.from_dict(cfg.to_dict())
    assert restored.cooldown_days_same_role == 90
    assert restored.cooldown_days_same_company == 30
    store.save(cfg)
    again = store.load()
    assert again.cooldown_days_same_role == 90
    assert again.cooldown_days_same_company == 30


def test_legacy_only_cooldown_leaves_windows_unset(data_dir):
    """A config JSON with only the legacy cooldown_days still loads unchanged.

    The new windows stay None so the cooldown resolver's fallback chain
    (window field -> legacy cooldown_days -> env -> 90) behaves exactly as
    before they existed.
    """
    (data_dir / "agent_config.json").write_text('{"cooldown_days": 14}', encoding="utf-8")
    cfg = store.load()
    assert cfg.cooldown_days == 14
    assert cfg.cooldown_days_same_role is None
    assert cfg.cooldown_days_same_company is None


def test_non_int_window_value_falls_back_to_none():
    """A hand-edited non-int window value degrades to None, never raises."""
    cfg = store.AgentConfig.from_dict(
        {"cooldown_days_same_role": "ninety", "cooldown_days_same_company": [30]}
    )
    assert cfg.cooldown_days_same_role is None
    assert cfg.cooldown_days_same_company is None


def test_job_profile_currency_defaults_to_none():
    """JobProfile has no regional default currency; the user states their own."""
    profile = store.JobProfile()
    assert profile.currency is None
    restored = store.JobProfile.from_dict(profile.to_dict())
    assert restored.currency is None


# --- Global job boards (migrated from per-profile preferred_sources) -------


def test_preferred_sources_migrates_to_job_boards_union():
    """Legacy per-profile preferred_sources fold into a single global,
    order-preserving, de-duplicated job_boards list; defaults are never seeded."""
    cfg = store.AgentConfig.from_dict(
        {
            "profiles": [
                {"preferred_sources": ["ashby", "custom.com"]},
                {"preferred_sources": ["ashby", "linkedin"]},
            ]
        }
    )
    sources = [b.source for b in cfg.job_boards]
    assert sources == ["ashby", "custom.com", "linkedin"]
    # Defaults beyond what was explicitly listed are absent from storage; they
    # only appear via resolved_board_sources().
    assert "greenhouse" not in sources
    assert "lever" not in sources
    assert "workday" not in sources


def test_resolved_board_sources_defaults_first():
    """The four defaults always lead; the operator's own boards follow,
    without duplicating a default they happen to name."""
    assert store.AgentConfig().resolved_board_sources() == [
        "ashby",
        "greenhouse",
        "lever",
        "workday",
    ]
    assert store.AgentConfig(
        job_boards=[store.JobBoard(source="linkedin")]
    ).resolved_board_sources() == ["ashby", "greenhouse", "lever", "workday", "linkedin"]
    assert store.AgentConfig(
        job_boards=[store.JobBoard(source="ashby")]
    ).resolved_board_sources() == ["ashby", "greenhouse", "lever", "workday"]


def test_job_board_round_trips_source_and_signin_url():
    cfg = store.AgentConfig(
        job_boards=[store.JobBoard(source="jobs.acme.com", signin_url="https://acme.com/login")]
    )
    restored = store.AgentConfig.from_dict(cfg.to_dict())
    assert restored.job_boards == cfg.job_boards


def test_malformed_job_boards_yields_empty_list():
    assert store.AgentConfig.from_dict({"job_boards": "not-a-list"}).job_boards == []
    assert store.AgentConfig.from_dict({"job_boards": [1, 2, 3]}).job_boards == []


def test_profile_with_legacy_preferred_sources_loads_without_error():
    cfg = store.AgentConfig.from_dict(
        {"profiles": [{"name": "p", "preferred_sources": ["ashby"]}]}
    )
    assert len(cfg.profiles) == 1
    assert cfg.profiles[0].name == "p"
    assert not hasattr(cfg.profiles[0], "preferred_sources")
