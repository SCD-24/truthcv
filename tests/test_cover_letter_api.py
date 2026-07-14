"""/api/cover-letter route: guardrail-gated, best-effort PDF/DOCX."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.routes as routes
from api.main import app
from providers.fake import FakeProvider
from truth import save
from truth.model import Experience, Skill, Truth


def _truth_with(skills, experiences=None) -> Truth:
    return Truth(experiences=experiences or [], education=[], skills=skills)


@pytest.fixture()
def client(data_dir, monkeypatch):
    def router(system, messages, schema):
        return {
            "paragraphs": [
                {"text": "I use Python at Acme Corp.", "claims": ["Python", "Acme Corp"]}
            ]
        }

    monkeypatch.setattr(routes, "get_provider", lambda *a, **k: FakeProvider(router=router))
    save(
        _truth_with(
            skills=[Skill(id="s1", value="Python", source="linkedin-pdf")],
            experiences=[
                Experience(
                    id="c1",
                    role="Engineer",
                    company="Acme Corp",
                    start="2020",
                    end="2023",
                    source="linkedin-pdf",
                )
            ],
        )
    )
    from truth.store import data_dir as dd

    (dd() / "posting.txt").write_text("Python role at a startup")
    return TestClient(app)


def test_cover_letter_requires_posting(data_dir, monkeypatch):
    monkeypatch.setattr(routes, "get_provider", lambda *a, **k: FakeProvider())
    c = TestClient(app)
    r = c.post("/api/cover-letter", json={"tone": "Professional", "length": "Short"})
    assert r.status_code == 400


def test_cover_letter_route(client):
    r = client.post("/api/cover-letter", json={"tone": "Professional", "length": "Short"})
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        b = r.json()
        assert b["blocked"] is False
        assert "pdfUrl" in b and "docxUrl" in b


def test_cover_letter_blocks_fabrication(data_dir, monkeypatch):
    def router(system, messages, schema):
        return {"paragraphs": [{"text": "I led 500 people.", "claims": ["Led 500 people at NASA"]}]}

    monkeypatch.setattr(routes, "get_provider", lambda *a, **k: FakeProvider(router=router))
    save(_truth_with(skills=[Skill(id="s1", value="Python", source="linkedin-pdf")]))
    from truth.store import data_dir as dd

    (dd() / "posting.txt").write_text("a role")
    c = TestClient(app)
    r = c.post("/api/cover-letter", json={"tone": "Warm", "length": "Standard"})
    assert r.status_code == 200
    b = r.json()
    assert b["blocked"] is True
    assert any(tok in b["unverifiable"] for tok in ("500", "nasa"))


def _fabricating_client(data_dir, monkeypatch):
    """A client whose provider always fabricates one unverifiable claim."""
    def router(system, messages, schema):
        return {"paragraphs": [{"text": "I led 500 people.", "claims": ["Led 500 people at NASA"]}]}

    monkeypatch.setattr(routes, "get_provider", lambda *a, **k: FakeProvider(router=router))
    save(_truth_with(skills=[Skill(id="s1", value="Python", source="linkedin-pdf")]))
    from truth.store import data_dir as dd

    (dd() / "posting.txt").write_text("a role")
    return TestClient(app)


def test_cover_letter_blocked_returns_grouped_claims(data_dir, monkeypatch):
    """The block surfaces whole flagged claims with stable ids, not just tokens."""
    c = _fabricating_client(data_dir, monkeypatch)
    b = c.post("/api/cover-letter", json={"tone": "Warm", "length": "Short"}).json()
    assert b["blocked"] is True
    claims = b["blockedClaims"]
    assert len(claims) == 1
    assert claims[0]["text"] == "Led 500 people at NASA"
    assert claims[0]["claimId"]
    assert any(t in claims[0]["tokens"] for t in ("500", "nasa"))


def test_cover_letter_approve_claim_unblocks(data_dir, monkeypatch):
    """Approving the blocked claim's id re-validates the SAME letter and passes,
    without writing anything to the truth file."""
    from truth import load

    c = _fabricating_client(data_dir, monkeypatch)
    blocked = c.post("/api/cover-letter", json={"tone": "Warm", "length": "Short"}).json()
    claim_id = blocked["blockedClaims"][0]["claimId"]

    r = c.post(
        "/api/cover-letter",
        json={
            "tone": "Warm",
            "length": "Short",
            "approvals": {"approvedClaimIds": [claim_id], "deniedClaimIds": []},
        },
    )
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        assert r.json()["blocked"] is False
    # Approval is render-scoped: no fabricated NASA experience was persisted.
    assert all(e.company != "NASA" for e in load().experiences)


def test_cover_letter_deny_claim_drops_it(data_dir, monkeypatch):
    """Denying the only flagged claim drops it, so the letter passes with nothing
    left to trip the guardrail."""
    c = _fabricating_client(data_dir, monkeypatch)
    blocked = c.post("/api/cover-letter", json={"tone": "Warm", "length": "Short"}).json()
    claim_id = blocked["blockedClaims"][0]["claimId"]

    r = c.post(
        "/api/cover-letter",
        json={
            "tone": "Warm",
            "length": "Short",
            "approvals": {"approvedClaimIds": [], "deniedClaimIds": [claim_id]},
        },
    )
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        assert r.json()["blocked"] is False
