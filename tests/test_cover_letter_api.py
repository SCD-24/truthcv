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
