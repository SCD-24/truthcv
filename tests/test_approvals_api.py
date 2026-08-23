"""Approval routes: the operator's surface, unreachable from the agent."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import companyboards.store as boards
import screening.store as store
from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _deferred(company="Grafana Labs", role="Staff AI Engineer"):
    return store.create({"company": company, "role": role, "verdict": "deferred"})


def test_list_filters_by_approval(client):
    _deferred()
    store.create({"company": "Pleo", "verdict": "rejected"})
    rows = client.get("/api/screenings?approval=pending").json()
    assert [r["company"] for r in rows] == ["Grafana Labs"]


def test_list_unfiltered_returns_everything(client):
    _deferred()
    store.create({"company": "Pleo", "verdict": "rejected"})
    assert len(client.get("/api/screenings").json()) == 2


def test_wire_model_exposes_approval_fields(client):
    _deferred()
    row = client.get("/api/screenings").json()[0]
    assert row["approval"] == "pending"
    assert row["applyAttempts"] == 0
    assert row["applyError"] == ""


def test_patch_sets_approval(client):
    s = _deferred()
    body = client.patch(f"/api/screenings/{s.id}", json={"approval": "approved"}).json()
    assert body["approval"] == "approved"
    assert store.get(s.id).approval == "approved"


def test_patch_unknown_id_404(client):
    assert client.patch("/api/screenings/nope", json={"approval": "approved"}).status_code == 404


def test_patch_bad_value_422(client):
    s = _deferred()
    assert client.patch(f"/api/screenings/{s.id}", json={"approval": "sure"}).status_code == 422


def test_bulk_patch_reports_per_id(client):
    a, b = _deferred("Grafana Labs"), _deferred("n8n")
    body = client.patch(
        "/api/screenings/approvals",
        json={"ids": [a.id, b.id, "missing"], "approval": "approved"},
    ).json()
    assert body["results"] == [
        {"id": a.id, "ok": True},
        {"id": b.id, "ok": True},
        {"id": "missing", "ok": False},
    ]
    assert store.get(a.id).approval == "approved"


def test_bulk_route_is_not_shadowed_by_the_id_route(client):
    """PATCH /screenings/approvals must not bind 'approvals' as an id."""
    resp = client.patch("/api/screenings/approvals", json={"ids": [], "approval": "approved"})
    assert resp.status_code == 200
    assert resp.json() == {"results": []}


def test_company_approval(client):
    boards.record("Grafana Labs", "https://grafana.com/careers")
    body = client.patch("/api/company-boards/Grafana Labs", json={"approved": True}).json()
    assert body["approved"] is True
    assert boards.load()["grafana labs"].approved is True


def test_company_approval_unknown_404(client):
    assert client.patch("/api/company-boards/Nobody", json={"approved": True}).status_code == 404


def test_no_agent_route_writes_approval(client):
    """The agent authenticates only against /api/agent/*. No path under that
    prefix may write approval, and no tool on its surface may either — the
    structural half of "the human approves, the agent never does"."""
    agent_paths = [
        r.path for r in app.routes if getattr(r, "path", "").startswith("/api/agent")
    ]
    assert agent_paths, "expected some /api/agent routes to exist"
    for path in agent_paths:
        assert "approval" not in path

    from agenttools.mcp_app import _TOOL_REGISTRY

    assert not any("approve" in name or "approval" in name for name in _TOOL_REGISTRY)
