"""Application Tracker API: CRUD, edited-document guardrail, and attach-on-render.

Rendering (WeasyPrint/pandoc) may be absent in CI, so save-and-render assertions
accept a 500 "backend unavailable" the same way tests/test_render.py skips.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.routes as routes
from api.main import app
from providers.fake import FakeProvider
from truth import Bullet, Experience, Skill, Truth, save


def _seed_truth() -> None:
    """A minimal truth so edited documents have facts to validate against."""
    save(
        Truth(
            experiences=[
                Experience(
                    id="exp-1",
                    role="Engineer",
                    company="Acme",
                    start="2020",
                    end="2023",
                    source="linkedin-pdf",
                    bullets=[Bullet("exp-1-b-1", "Built a payments API in Python", "linkedin-pdf")],
                )
            ],
            skills=[Skill("sk-python", "Python", "linkedin-pdf")],
        )
    )


@pytest.fixture()
def client(data_dir, monkeypatch):
    provider = FakeProvider(router=lambda *a, **k: {})
    monkeypatch.setattr(routes, "get_provider", lambda *a, **k: provider)
    return TestClient(app)


# --- CRUD ----------------------------------------------------------------------

def test_create_list_update_delete(client):
    # Create (General submission — no posting).
    r = client.post(
        "/api/applications",
        json={
            "company": "Nagarro",
            "website": "https://www.nagarro.com/en/",
            "applicationUrl": "N/A",
            "submitted": True,
            "submissionType": "General",
            "reachedOut": True,
            "toWho": "Patricia Pavelescu",
            "responseReceived": False,
            "method": "Linkedin",
            "applicationDate": "2026-07-01",
            "notes": "Referred by a friend on the platform team.",
        },
    )
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    assert r.json()["company"] == "Nagarro"
    assert r.json()["posting"] == ""
    assert r.json()["applicationDate"] == "2026-07-01"
    assert r.json()["notes"] == "Referred by a friend on the platform team."

    # List.
    r = client.get("/api/applications")
    assert r.status_code == 200
    assert any(a["id"] == app_id for a in r.json())

    # Update a status flag plus the date and notes.
    r = client.put(
        f"/api/applications/{app_id}",
        json={
            "responseReceived": True,
            "applicationDate": "2026-07-05",
            "notes": "Heard back — phone screen scheduled.",
        },
    )
    assert r.status_code == 200
    assert r.json()["responseReceived"] is True
    assert r.json()["applicationDate"] == "2026-07-05"
    assert r.json()["notes"] == "Heard back — phone screen scheduled."
    assert r.json()["company"] == "Nagarro"  # untouched

    # Delete.
    assert client.delete(f"/api/applications/{app_id}").status_code == 204
    assert client.delete(f"/api/applications/{app_id}").status_code == 404


def test_update_unknown_returns_404(client):
    assert client.put("/api/applications/nope", json={"company": "X"}).status_code == 404


# --- Edited-document guardrail -------------------------------------------------

def test_edited_cv_blocked_when_it_strays_from_truth(client):
    _seed_truth()
    app_id = client.post("/api/applications", json={"company": "Acme"}).json()["id"]

    # "Rust" and "Kubernetes" are not in the truth -> must be blocked, no render.
    r = client.put(
        f"/api/applications/{app_id}/cv",
        json={"html": "<p>Expert in Rust and Kubernetes orchestration</p>"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["blocked"] is True
    assert body["application"] is None
    tokens = {t for c in body["blockedClaims"] for t in c["tokens"]}
    assert "rust" in tokens and "kubernetes" in tokens


def test_edited_cv_passes_and_saves_when_truthful(client):
    _seed_truth()
    app_id = client.post("/api/applications", json={"company": "Acme"}).json()["id"]

    r = client.put(
        f"/api/applications/{app_id}/cv",
        json={"html": "<p>Built a payments API in Python at Acme</p>"},
    )
    # Passes the guardrail; render may still be unavailable in CI.
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        body = r.json()
        assert body["blocked"] is False
        assert body["application"]["cvDocument"]["source"].startswith("<p>Built")


def test_edited_cover_letter_guardrail(client):
    _seed_truth()
    app_id = client.post("/api/applications", json={"company": "Acme"}).json()["id"]

    r = client.put(
        f"/api/applications/{app_id}/cover-letter",
        json={"text": "I led a blockchain migration at Acme."},
    )
    assert r.status_code == 200
    assert r.json()["blocked"] is True
    tokens = {t for c in r.json()["blockedClaims"] for t in c["tokens"]}
    assert "blockchain" in tokens


def test_save_document_unknown_application_404(client):
    _seed_truth()
    assert client.put("/api/applications/nope/cv", json={"html": "<p>Python</p>"}).status_code == 404


def test_edited_cv_persists_link_when_render_unavailable(client, monkeypatch):
    """A missing render backend must NOT lose the saved CV.

    save_cv_document only records source + filenames, and _download_url nulls
    links for files that were never produced, so the CV link persists even when
    WeasyPrint/pandoc are both absent. This pins that best-effort contract.
    """
    from render.pdf import RenderUnavailable

    def _unavailable(*_a, **_k):
        raise RenderUnavailable("no backend")

    monkeypatch.setattr(routes, "render_pdf", _unavailable)
    monkeypatch.setattr(routes, "render_docx", _unavailable)

    _seed_truth()
    app_id = client.post("/api/applications", json={"company": "Acme"}).json()["id"]

    r = client.put(
        f"/api/applications/{app_id}/cv",
        json={"html": "<p>Built a payments API in Python at Acme</p>"},
    )
    # Save-before-render: the request succeeds and the source is recorded even
    # though nothing could be rendered.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blocked"] is False
    assert body["application"]["cvDocument"]["source"].startswith("<p>Built")
    # Regression: the save succeeds AND signals that no PDF/DOCX was produced, so
    # the UI can say "saved, but the PDF couldn't be generated" instead of the
    # save silently looking like it did nothing.
    assert body["renderUnavailable"] is True
    assert body["application"]["cvDocument"]["pdfUrl"] is None
    assert body["application"]["cvDocument"]["docxUrl"] is None


def test_edited_cover_letter_persists_link_when_render_unavailable(client, monkeypatch):
    """The same best-effort save contract for an edited cover letter."""
    from render.pdf import RenderUnavailable

    def _unavailable(*_a, **_k):
        raise RenderUnavailable("no backend")

    monkeypatch.setattr(routes, "render_pdf", _unavailable)
    monkeypatch.setattr(routes, "render_docx", _unavailable)

    _seed_truth()
    app_id = client.post("/api/applications", json={"company": "Acme"}).json()["id"]

    r = client.put(
        f"/api/applications/{app_id}/cover-letter",
        json={"text": "Built a payments API in Python at Acme."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blocked"] is False
    assert body["application"]["coverLetterDocument"]["source"].startswith("Built")
    assert body["renderUnavailable"] is True


# --- Attach on render / cover-letter ------------------------------------------

def test_cover_letter_attaches_to_application(client, monkeypatch):
    _seed_truth()
    app_id = client.post("/api/applications", json={"company": "Acme"}).json()["id"]

    # A posting must exist for /cover-letter; fake the letter build to a truthful
    # single claim so the guardrail passes deterministically.
    from truth.store import data_dir

    (data_dir() / "posting.txt").write_text("Senior Engineer", encoding="utf-8")
    monkeypatch.setattr(
        "coverletter.build_letter",
        lambda *a, **k: {"blocked": False, "unverifiable": [], "text": "Built a payments API in Python."},
    )

    r = client.post("/api/cover-letter", json={"applicationId": app_id})
    assert r.status_code in (200, 500), r.text
    if r.status_code == 200:
        # The document is now recorded on the application.
        app = next(a for a in client.get("/api/applications").json() if a["id"] == app_id)
        assert app["coverLetterDocument"] is not None
        assert app["coverLetterDocument"]["source"].startswith("Built a payments")
