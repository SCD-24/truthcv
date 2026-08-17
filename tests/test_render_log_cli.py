"""The CLI must not let a failed ledger load destroy a good log.

`store.load_all()` fails safe to `[]`, and the completeness guard is vacuously
satisfied by an empty list — so without a check upstream of it, a transient
read error or a hand-edit typo in `applications.json` would atomically replace
a log accounting for every application with a header and nothing else, and
report success. Silent omission is the failure the whole module exists to
prevent; these tests pin its likeliest cause.
"""

import json

import pytest

from applications.log_render import RenderRefused
import scripts.render_application_log as cli


@pytest.fixture
def volume(tmp_path, monkeypatch):
    """A data volume with a two-record ledger and an existing rendered log."""
    ledger = tmp_path / "applications.json"
    ledger.write_text(
        json.dumps(
            [
                {"id": "aaa111aaa111", "company": "Acme GmbH"},
                {"id": "bbb222bbb222", "company": "Beta AG"},
            ]
        )
    )
    monkeypatch.setattr(cli.app_store, "applications_path", lambda: ledger)
    monkeypatch.setattr(cli, "default_log_path", lambda: tmp_path / "log" / "APPLICATION_LOG.md")
    return tmp_path, ledger


def test_a_whole_ledger_renders(volume, capsys):
    """The happy path still works — the guard is not simply refusing always."""
    tmp_path, _ = volume
    assert cli.main([]) == 0
    text = (tmp_path / "log" / "APPLICATION_LOG.md").read_text()
    assert text.count("<!-- record: aaa111aaa111 -->") == 1
    assert text.count("<!-- record: bbb222bbb222 -->") == 1


def test_a_partly_loaded_ledger_is_refused_and_the_log_survives(volume, monkeypatch, capsys):
    """One unloadable record must not silently vanish from the log."""
    tmp_path, _ = volume
    assert cli.main([]) == 0
    good = (tmp_path / "log" / "APPLICATION_LOG.md").read_text()

    survivors = cli.app_store.load_all()[:1]
    monkeypatch.setattr(cli.app_store, "load_all", lambda: survivors)
    assert cli.main([]) == 1
    assert (tmp_path / "log" / "APPLICATION_LOG.md").read_text() == good
    assert "REFUSED" in capsys.readouterr().err


def test_an_empty_load_over_a_populated_ledger_is_refused(volume, monkeypatch, capsys):
    """`load_all()` failing safe to [] must not empty the log."""
    tmp_path, _ = volume
    assert cli.main([]) == 0
    good = (tmp_path / "log" / "APPLICATION_LOG.md").read_text()

    monkeypatch.setattr(cli.app_store, "load_all", list)
    assert cli.main([]) == 1
    assert (tmp_path / "log" / "APPLICATION_LOG.md").read_text() == good
    assert "refusing to render a log that would omit the rest" in capsys.readouterr().err


def test_a_malformed_ledger_is_refused(volume, monkeypatch, capsys):
    """A hand-edit typo must not read as "there are no applications"."""
    tmp_path, ledger = volume
    assert cli.main([]) == 0
    good = (tmp_path / "log" / "APPLICATION_LOG.md").read_text()

    ledger.write_text("{ not json")
    monkeypatch.setattr(cli.app_store, "load_all", list)
    assert cli.main([]) == 1
    assert (tmp_path / "log" / "APPLICATION_LOG.md").read_text() == good
    assert "could not be read" in capsys.readouterr().err


def test_a_missing_ledger_with_nothing_loaded_is_refused(volume, monkeypatch, capsys):
    """An unmounted volume must not be mistaken for an empty ledger."""
    tmp_path, ledger = volume
    ledger.unlink()
    monkeypatch.setattr(cli.app_store, "load_all", list)
    assert cli.main([]) == 1
    assert "refusing to render an empty log" in capsys.readouterr().err


def test_dry_run_is_checked_too(volume, monkeypatch, capsys):
    """--dry-run reports the same refusal rather than a reassuring count."""
    monkeypatch.setattr(cli.app_store, "load_all", list)
    assert cli.main(["--dry-run"]) == 1
    assert "REFUSED" in capsys.readouterr().err


def test_check_ledger_loaded_whole_raises_render_refused(volume, monkeypatch):
    """The check reports through the module's own refusal type."""
    with pytest.raises(RenderRefused):
        cli.check_ledger_loaded_whole([])
