"""Startup purge of legacy 'unreadable' screenings runs once from the lifespan."""

from __future__ import annotations

import contextlib
import json
import logging

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
from api.main import app
from coverletter import store as letters
from screening import store

MARKER = ".purge_unreadable_screenings.v1.done"
BACKUP = "screenings.pre-unreadable-purge.bak.json"


@pytest.fixture(autouse=True)
def no_session_managers(monkeypatch):
    """Stub the MCP session managers' ``run()`` (enterable once per process)."""

    @contextlib.asynccontextmanager
    async def _noop():
        yield

    monkeypatch.setattr(main_mod._mcp_server.session_manager, "run", _noop)
    monkeypatch.setattr(main_mod.diagnostics_session_manager, "run", _noop)


def _rec(rid, blocker="", approval="", verdict=""):
    return {
        "id": rid,
        "company": "Acme",
        "role": "Dev",
        "url": f"https://acme.example/jobs/{rid}",
        "verdict": verdict,
        "screening_blocker": blocker,
        "approval": approval,
    }


def _seed(items):
    p = store.screenings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items), encoding="utf-8")


def _ids():
    return {s.id for s in store.load_all()}


def _full_seed():
    _seed(
        [
            _rec("u-pending", "unreadable", "pending"),
            _rec("u-rejected", "unreadable", "rejected"),
            _rec("u-empty", "unreadable", ""),
            _rec("u-applied", "unreadable", "applied"),
            _rec("login", "login_required", "pending"),
            _rec("normal", "", "rejected", verdict="rejected"),
        ]
    )


def test_startup_purges_unprotected_unreadable(data_dir):
    _full_seed()
    letters.save("u-pending", letters.CoverLetterDraft(text="hi"))
    with TestClient(app):
        pass
    assert _ids() == {"u-applied", "login", "normal"}
    assert (data_dir / MARKER).exists()
    assert (data_dir / BACKUP).exists()
    assert letters.load("u-pending") is None


def test_startup_keeps_unreadable_referenced_by_an_application(data_dir):
    _seed([_rec("u-ref", "unreadable", "pending"), _rec("u-gone", "unreadable", "pending")])
    (data_dir / "applications.json").write_text(
        json.dumps([{"id": "app1", "screening_id": "u-ref"}]), encoding="utf-8"
    )
    with TestClient(app):
        pass
    assert _ids() == {"u-ref"}


def test_second_startup_does_not_purge_again(data_dir):
    _full_seed()
    with TestClient(app):
        pass
    _seed([_rec("late", "unreadable", "pending")])
    with TestClient(app):
        pass
    assert _ids() == {"late"}


def test_startup_survives_purge_failure(monkeypatch, caplog):
    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(main_mod, "purge_unreadable_once", boom)
    with caplog.at_level(logging.INFO):
        with TestClient(app) as c:
            assert c.get("/api/profile").status_code == 200
    assert any(
        r.name == "api.main" and r.levelno == logging.ERROR for r in caplog.records
    )


def test_nothing_to_delete_writes_marker_without_backup(data_dir):
    _seed([_rec("normal", "", "rejected", verdict="rejected")])
    with TestClient(app):
        pass
    assert (data_dir / MARKER).exists()
    assert not (data_dir / BACKUP).exists()
    assert _ids() == {"normal"}
