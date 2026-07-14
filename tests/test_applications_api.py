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

def test_manual_cv_edit_is_trusted_and_saved(client):
    """A manual edit is a deliberate human decision, so it is saved as-is —
    the truthfulness guardrail no longer gates hand-edited documents, only the
    automatic AI generation. Even tokens absent from the truth file persist.
    """
    _seed_truth()
    app_id = client.post("/api/applications", json={"company": "Acme"}).json()["id"]

    r = client.put(
        f"/api/applications/{app_id}/cv",
        json={"html": "<p>Expert in Rust and Kubernetes orchestration</p>"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blocked"] is False
    assert body["application"] is not None
    assert body["application"]["cvDocument"]["source"].startswith("<p>Expert")
    # And it shows as attached in the ledger.
    listed = client.get("/api/applications").json()
    saved = next(a for a in listed if a["id"] == app_id)
    assert saved["cvDocument"] is not None


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


def test_rendered_cv_with_profile_header_resaves_and_attaches(client):
    """Re-saving a rendered CV (which always prints the profile header) must not
    be blocked on the header's identity tokens, and must attach + appear in the
    ledger. Regression: the header was previously omitted from the allowed set,
    so a document TruthCV itself produced could never be re-saved.
    """
    from truth import Link, Profile

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
                    bullets=[
                        Bullet(
                            "exp-1-b-1",
                            "Built a payments API in Python",
                            "linkedin-pdf",
                        )
                    ],
                )
            ],
            skills=[Skill("sk-python", "Python", "linkedin-pdf")],
            profile=Profile(
                name="Jane Q. Rivera",
                email="jane.rivera@example.com",
                phone="+1 555 0100",
                location="Berlin, Germany",
                links=[Link(label="LinkedIn", url="linkedin.com/in/jrivera")],
                summary="Engineer who built a payments API in Python at Acme.",
            ),
        )
    )
    app_id = client.post("/api/applications", json={"company": "Acme"}).json()["id"]

    # A rendered-CV-shaped document: profile header + a truthful experience line.
    html = (
        "<h1>Jane Q. Rivera</h1>"
        "<p>jane.rivera@example.com · +1 555 0100 · Berlin, Germany · "
        "linkedin.com/in/jrivera</p>"
        "<p>Engineer who built a payments API in Python at Acme.</p>"
        "<p>Built a payments API in Python at Acme</p>"
    )
    r = client.put(f"/api/applications/{app_id}/cv", json={"html": html})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blocked"] is False, body.get("unverifiable")
    assert body["application"]["cvDocument"] is not None

    # And it shows as attached in the ledger (no more "+ Add CV").
    listed = client.get("/api/applications").json()
    saved = next(a for a in listed if a["id"] == app_id)
    assert saved["cvDocument"] is not None


def test_manual_cover_letter_edit_is_trusted_and_saved(client):
    """Manual cover-letter edits are trusted and saved as-is (guardrail no longer
    gates hand-edited documents)."""
    _seed_truth()
    app_id = client.post("/api/applications", json={"company": "Acme"}).json()["id"]

    r = client.put(
        f"/api/applications/{app_id}/cover-letter",
        json={"text": "I led a blockchain migration at Acme."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blocked"] is False
    assert body["application"] is not None
    assert body["application"]["coverLetterDocument"] is not None


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


# --- Export --------------------------------------------------------------------

def test_export_returns_zip_with_csv_and_company_folders(client):
    """The export bundles the whole table as a CSV plus each application's
    existing rendered files under a per-company folder, zipped for download."""
    import io
    import zipfile

    from truth.store import data_dir

    import applications as app_store

    # Two applications; give the first a rendered CV file on the volume.
    with_docs = client.post(
        "/api/applications",
        json={"company": "Acme Corp", "applicationDate": "2026-07-01"},
    ).json()["id"]
    client.post("/api/applications", json={"company": "Globex"})

    cv_pdf, _ = app_store.cv_filenames(with_docs)
    (data_dir() / cv_pdf).write_bytes(b"%PDF-1.4 fake")

    r = client.get("/api/applications/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert 'filename="applications.zip"' in r.headers["content-disposition"]

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()

    # CSV at the root, with a header row plus one row per application.
    assert "applications.csv" in names
    csv_text = zf.read("applications.csv").decode()
    assert "company" in csv_text.splitlines()[0]
    assert "Acme Corp" in csv_text
    assert "Globex" in csv_text

    # The application with a rendered file gets a per-company folder; the one
    # without any files does not.
    assert f"Acme Corp/{cv_pdf}" in names
    assert not any(n.startswith("Globex/") for n in names)


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
