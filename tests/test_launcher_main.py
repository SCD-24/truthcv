"""The bootstrap CLI, exercised against a temp repository.

stdout carries exactly one machine-readable KEY=value line so the per-OS
shims can read the port without parsing prose; everything a human reads goes
to stderr.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from launcher import __main__ as bootstrap
from launcher import envfile

EXAMPLE = """LLM_PROVIDER=anthropic
ENCRYPTION_KEY=
AGENT_API_TOKEN=
"""


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    return tmp_path


def test_creates_env_with_every_required_key(repo: Path, capsys):
    assert bootstrap.main(["--repo", str(repo)]) == 0

    values = envfile.parse((repo / ".env").read_text(encoding="utf-8"))
    assert len(values["ENCRYPTION_KEY"]) > 0
    assert len(values["AGENT_API_TOKEN"]) == 64
    assert values["APP_PORT"] == "5627"
    assert values["NOVNC_HOST_PORT"] == "5628"


def test_prints_the_app_port_as_the_only_stdout_line(repo: Path, capsys):
    bootstrap.main(["--repo", str(repo)])

    captured = capsys.readouterr()
    assert captured.out.strip() == "APP_PORT=5627"
    assert captured.err != ""


def test_does_not_rotate_existing_secrets(repo: Path):
    env = repo / ".env"
    env.write_text(
        "ENCRYPTION_KEY=mine\nAGENT_API_TOKEN=also-mine\nAPP_PORT=9999\n"
        "NOVNC_HOST_PORT=9998\n",
        encoding="utf-8",
    )
    original = env.read_text(encoding="utf-8")

    bootstrap.main(["--repo", str(repo)])

    assert env.read_text(encoding="utf-8") == original


def test_reports_the_stored_port_not_the_default(repo: Path, capsys):
    (repo / ".env").write_text(
        "ENCRYPTION_KEY=k\nAGENT_API_TOKEN=t\nAPP_PORT=9999\nNOVNC_HOST_PORT=9998\n",
        encoding="utf-8",
    )

    bootstrap.main(["--repo", str(repo)])

    assert capsys.readouterr().out.strip() == "APP_PORT=9999"


def test_bump_advances_the_named_port(repo: Path, capsys):
    bootstrap.main(["--repo", str(repo)])
    capsys.readouterr()

    assert bootstrap.main(["--repo", str(repo), "--bump", "APP_PORT"]) == 0

    values = envfile.parse((repo / ".env").read_text(encoding="utf-8"))
    # 5628 is the noVNC default, so the app port skips it.
    assert values["APP_PORT"] == "5629"
    assert values["NOVNC_HOST_PORT"] == "5628"
    assert capsys.readouterr().out.strip() == "APP_PORT=5629"


def test_bump_leaves_secrets_untouched(repo: Path):
    bootstrap.main(["--repo", str(repo)])
    before = envfile.parse((repo / ".env").read_text(encoding="utf-8"))

    bootstrap.main(["--repo", str(repo), "--bump", "APP_PORT"])

    after = envfile.parse((repo / ".env").read_text(encoding="utf-8"))
    assert after["ENCRYPTION_KEY"] == before["ENCRYPTION_KEY"]
    assert after["AGENT_API_TOKEN"] == before["AGENT_API_TOKEN"]


def test_bump_rejects_an_unknown_variable(repo: Path):
    bootstrap.main(["--repo", str(repo)])
    assert bootstrap.main(["--repo", str(repo), "--bump", "NOPE"]) == 2


def test_bump_without_an_env_file_fails_clearly(repo: Path, capsys):
    assert bootstrap.main(["--repo", str(repo), "--bump", "APP_PORT"]) == 2
    assert "run without --bump first" in capsys.readouterr().err


def test_missing_env_example_fails_clearly_instead_of_a_traceback(tmp_path: Path, capsys):
    # No .env.example written into tmp_path, and no .env either.
    assert bootstrap.main(["--repo", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""
