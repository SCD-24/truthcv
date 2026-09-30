"""Startup company-claims migration runs from the app lifespan."""

from __future__ import annotations

import contextlib
import json
import logging

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
from api.main import app
from companyresearch import store as findings_store

SECRET_VALUE = "SECRET-VALUE-4711"


@pytest.fixture(autouse=True)
def no_session_managers(monkeypatch):
    """Stub the MCP session managers' ``run()`` with a no-op context manager.

    StreamableHTTPSessionManager.run() may be entered only once per process,
    and tests/test_mcp_transport.py's module fixture owns that one entry.
    Entering the lifespan here must not enter it a second time.
    """

    @contextlib.asynccontextmanager
    async def _noop():
        yield

    monkeypatch.setattr(main_mod._mcp_server.session_manager, "run", _noop)
    monkeypatch.setattr(main_mod.diagnostics_session_manager, "run", _noop)


def _finding(fid, claim, value="v", company="Acme Co"):
    return {
        "id": fid,
        "company": company,
        "claim": claim,
        "value": value,
        "source_url": "https://x.example",
        "source_class": "press",
        "observed_at": "2026-01-01",
        "recorded_by": "agent",
    }


def _seed(items):
    p = findings_store.findings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items), encoding="utf-8")


def test_startup_migrates_legacy_claims():
    _seed([_finding("a", "Glassdoor rating")])
    with TestClient(app):
        pass
    path = findings_store.findings_path()
    item = json.loads(path.read_text(encoding="utf-8"))[0]
    assert item["claim"] == "employer_rating"
    assert item["claim_label"] == "Glassdoor rating"
    assert len(list(path.parent.glob("company_findings.*.bak.json"))) == 1


def test_startup_survives_migration_failure(monkeypatch, caplog):
    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(main_mod, "migrate_claims_if_needed", boom)
    with caplog.at_level(logging.INFO):
        with TestClient(app) as c:
            assert c.get("/api/profile").status_code == 200
    assert any(
        r.name == "api.main" and r.levelno == logging.ERROR for r in caplog.records
    )


def test_startup_log_does_not_leak_values(caplog):
    _seed([_finding("a", "Glassdoor rating", value=SECRET_VALUE)])
    with caplog.at_level(logging.INFO):
        with TestClient(app):
            pass
    assert any("company-claims migration" in r.getMessage() for r in caplog.records)
    for r in caplog.records:
        assert SECRET_VALUE not in r.getMessage()
        assert SECRET_VALUE not in repr(r.__dict__)
