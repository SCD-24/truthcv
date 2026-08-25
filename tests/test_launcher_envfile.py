"""The .env safety rules.

These are the tests that matter most in this plan: a bug here destroys a
real configuration file that the user cannot reconstruct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from launcher import envfile

EXAMPLE = """# Which provider
LLM_PROVIDER=anthropic

# Master key
ENCRYPTION_KEY=

# Shared secret
AGENT_API_TOKEN=
"""


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    return tmp_path


def test_parse_skips_comments_and_blanks():
    parsed = envfile.parse("# note\n\nA=1\nB = 2\nnot-a-pair\n")
    assert parsed == {"A": "1", "B": "2"}


def test_generated_encryption_key_is_a_valid_fernet_key():
    from cryptography.fernet import Fernet

    Fernet(envfile.generate_encryption_key().encode())


def test_generated_agent_token_is_64_hex_chars():
    token = envfile.generate_agent_token()
    assert len(token) == 64
    int(token, 16)


def test_creates_env_from_example_when_absent(repo: Path):
    result = envfile.ensure(
        repo / ".env", repo / ".env.example", {"ENCRYPTION_KEY": "k", "AGENT_API_TOKEN": "t"}
    )
    assert result.created is True
    assert result.backup_path is None
    written = (repo / ".env").read_text(encoding="utf-8")
    assert "ENCRYPTION_KEY=k" in written
    assert "AGENT_API_TOKEN=t" in written
    assert "LLM_PROVIDER=anthropic" in written


def test_complete_env_is_never_opened_for_writing(repo: Path):
    env = repo / ".env"
    original = "ENCRYPTION_KEY=mine\nAGENT_API_TOKEN=also-mine\n"
    env.write_text(original, encoding="utf-8")
    before = env.stat().st_mtime_ns

    result = envfile.ensure(
        env, repo / ".env.example", {"ENCRYPTION_KEY": "new", "AGENT_API_TOKEN": "new"}
    )

    assert result.created is False
    assert result.filled == []
    assert result.appended == []
    assert result.backup_path is None
    assert env.read_text(encoding="utf-8") == original
    assert env.stat().st_mtime_ns == before


def test_blank_assignment_is_filled_in_place(repo: Path):
    env = repo / ".env"
    env.write_text("# my note\nLLM_PROVIDER=openai\nENCRYPTION_KEY=\n", encoding="utf-8")

    result = envfile.ensure(env, repo / ".env.example", {"ENCRYPTION_KEY": "generated"})

    assert result.filled == ["ENCRYPTION_KEY"]
    assert result.appended == []
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# my note"
    assert lines[1] == "LLM_PROVIDER=openai"
    assert lines[2] == "ENCRYPTION_KEY=generated"
    assert envfile.MANAGED_HEADER not in env.read_text(encoding="utf-8")


def test_blank_assignment_does_not_produce_a_duplicate_key(repo: Path):
    env = repo / ".env"
    env.write_text("ENCRYPTION_KEY=\n", encoding="utf-8")

    envfile.ensure(env, repo / ".env.example", {"ENCRYPTION_KEY": "generated"})

    text = env.read_text(encoding="utf-8")
    assert text.count("ENCRYPTION_KEY=") == 1


def test_absent_key_is_appended_under_a_marked_header(repo: Path):
    env = repo / ".env"
    env.write_text("LLM_PROVIDER=openai\n", encoding="utf-8")

    result = envfile.ensure(env, repo / ".env.example", {"AGENT_API_TOKEN": "tok"})

    assert result.appended == ["AGENT_API_TOKEN"]
    assert result.filled == []
    text = env.read_text(encoding="utf-8")
    assert text.startswith("LLM_PROVIDER=openai\n")
    assert envfile.MANAGED_HEADER in text
    assert text.rstrip().endswith("AGENT_API_TOKEN=tok")


def test_existing_values_and_comments_survive_byte_for_byte(repo: Path):
    env = repo / ".env"
    original = "# careful\nLLM_PROVIDER=openai   # trailing note\n\nOPENAI_API_KEY=sk-real\n"
    env.write_text(original, encoding="utf-8")

    envfile.ensure(env, repo / ".env.example", {"AGENT_API_TOKEN": "tok"})

    text = env.read_text(encoding="utf-8")
    assert text.startswith(original)


def test_backup_written_before_any_change(repo: Path):
    env = repo / ".env"
    original = "LLM_PROVIDER=openai\n"
    env.write_text(original, encoding="utf-8")

    result = envfile.ensure(env, repo / ".env.example", {"AGENT_API_TOKEN": "tok"})

    assert result.backup_path is not None
    assert result.backup_path.read_text(encoding="utf-8") == original
    assert result.backup_path.name.startswith(".env.backup-")


def test_rerunning_on_a_complete_env_is_a_noop(repo: Path):
    env = repo / ".env"
    envfile.ensure(env, repo / ".env.example", {"ENCRYPTION_KEY": "k", "AGENT_API_TOKEN": "t"})
    after_first = env.read_text(encoding="utf-8")

    result = envfile.ensure(
        env, repo / ".env.example", {"ENCRYPTION_KEY": "other", "AGENT_API_TOKEN": "other"}
    )

    assert result.filled == []
    assert result.appended == []
    assert env.read_text(encoding="utf-8") == after_first


def test_set_value_replaces_a_valued_line_and_backs_up(repo: Path):
    env = repo / ".env"
    env.write_text("# note\nAPP_PORT=5627\nLLM_PROVIDER=openai\n", encoding="utf-8")

    backup_path = envfile.set_value(env, "APP_PORT", "5629")

    assert backup_path.read_text(encoding="utf-8").count("APP_PORT=5627") == 1
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines == ["# note", "APP_PORT=5629", "LLM_PROVIDER=openai"]


def test_set_value_appends_when_the_key_is_absent(repo: Path):
    env = repo / ".env"
    env.write_text("LLM_PROVIDER=openai\n", encoding="utf-8")

    envfile.set_value(env, "APP_PORT", "5629")

    assert "APP_PORT=5629" in env.read_text(encoding="utf-8")
