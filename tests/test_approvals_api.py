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


def test_patch_sets_url_only(client):
    s = _deferred()
    body = client.patch(f"/api/screenings/{s.id}", json={"url": "https://x.com/1"}).json()
    assert body["url"] == "https://x.com/1"
    assert body["approval"] == "pending"
    reloaded = store.get(s.id)
    assert reloaded.url == "https://x.com/1"
    assert reloaded.approval == "pending"


def test_patch_sets_url_and_approval(client):
    s = _deferred()
    body = client.patch(
        f"/api/screenings/{s.id}",
        json={"url": "https://x.com/1", "approval": "approved"},
    ).json()
    assert body["url"] == "https://x.com/1"
    assert body["approval"] == "approved"
    reloaded = store.get(s.id)
    assert reloaded.url == "https://x.com/1"
    assert reloaded.approval == "approved"


def test_patch_empty_body_422(client):
    s = _deferred()
    assert client.patch(f"/api/screenings/{s.id}", json={}).status_code == 422


def test_patch_url_unknown_id_404(client):
    assert client.patch("/api/screenings/nope", json={"url": "https://x.com/1"}).status_code == 404


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


def test_company_approval_without_a_resolved_board(client):
    """The queue is full of companies screened from a posting URL, which have no
    board entry; approving one records the trust rather than 404ing."""
    resp = client.patch("/api/company-boards/Nobody", json={"approved": True})
    assert resp.status_code == 200
    assert resp.json()["approved"] is True
    assert boards.load()["nobody"].approved is True


def test_no_agent_route_writes_approval(client):
    """The agent authenticates only against /api/agent/*. No path under that
    prefix may write approval, and no tool on its surface may either — the
    structural half of "the human approves, the agent never does"."""
    paths = app.openapi()["paths"]
    agent_paths = [p for p in paths if p.startswith("/api/agent")]
    assert agent_paths, "expected some /api/agent routes to exist"
    for path in agent_paths:
        assert "approval" not in path

    # And the approval writers are reachable only outside that prefix.
    approval_paths = [p for p in paths if "approval" in p]
    assert approval_paths, "expected the approval routes to exist"
    assert not any(p.startswith("/api/agent") for p in approval_paths)

    # No tool on the agent's surface can WRITE approval. Checked against the
    # store functions themselves rather than tool names: the surface legitimately
    # includes get_approved_applications, which only reads.
    import screening.store as store_module
    from agenttools.mcp_app import _TOOL_REGISTRY

    writers = {store_module.set_approval, store_module.mark_applied}
    assert not (writers & {fn for fn, _ in _TOOL_REGISTRY.values()})
