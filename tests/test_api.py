"""Full-wizard API integration tests with the fake provider (no network).

Extraction, tailoring, and inference are all faked via a schema-aware router, so
the whole upload -> extract -> tailor -> confirm -> render flow runs offline and
deterministically against the structured (experiences/education/skills) contract.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

import api.routes as routes
from api.main import app
from providers.fake import FakeProvider


def _router(system, messages, schema):
    """Schema-shaped fake responses for each LLM call in the wizard flow."""
    props = (schema or {}).get("properties", {})
    # Extraction: group the profile into experiences / education / skills.
    if "experiences" in props and "education" in props:
        return {
            "experiences": [
                {
                    "role": "Senior Software Engineer",
                    "company": "Acme Corp",
                    "start": "2020",
                    "end": "2023",
                    "bullets": ["Built a payments API in Python"],
                }
            ],
            "education": [],
            "skills": ["Python"],
        }
    # Keyword extraction.
    if "keywords" in props:
        return {"keywords": ["Python"]}
    # Select & rephrase: unknown ids -> select falls back to verbatim truth.
    if "experiences" in props and "skills" in props:
        return {"experiences": [], "skills": []}
    # Inference detection.
    if "inferences" in props:
        return {
            "inferences": [
                {"claim": "Experience with Kubernetes", "rationale": "posting"}
            ]
        }
    return {}


@pytest.fixture()
def client(data_dir, monkeypatch):
    provider = FakeProvider(router=_router)
    monkeypatch.setattr(routes, "get_provider", lambda *a, **k: provider)
    return TestClient(app)


# A minimal, valid single-page PDF containing selectable text so /upload's
# text-extraction step sees non-empty content (extraction itself is faked).
_HANDWRITTEN_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]"
    b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\n"
    b"BT /F1 12 Tf 20 100 Td (Profile text) Tj ET\n"
    b"endstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"xref\n0 6\n0000000000 65535 f \n"
    b"trailer<</Root 1 0 R/Size 6>>\nstartxref\n0\n%%EOF"
)


def test_full_happy_path(client):
    # upload
    r = client.post(
        "/api/upload",
        files={"file": ("cv.pdf", io.BytesIO(_HANDWRITTEN_PDF), "application/pdf")},
    )
    assert r.status_code == 204, r.text

    # extract -> structured TruthDoc
    r = client.post("/api/extract")
    assert r.status_code == 200
    doc = r.json()
    assert set(doc.keys()) == {"experiences", "education", "skills", "profile"}
    exp = doc["experiences"][0]
    assert exp["role"] == "Senior Software Engineer"
    assert exp["source"] == "linkedin-pdf"
    assert exp["bullets"][0]["value"] == "Built a payments API in Python"
    assert doc["skills"][0]["value"] == "Python"

    # truth GET round-trips the same structure
    r = client.get("/api/truth")
    assert r.status_code == 200
    got = r.json()
    assert len(got["experiences"]) == 1
    assert len(got["skills"]) == 1

    # tailor
    r = client.post("/api/tailor", json={"posting": "Python and Kubernetes role"})
    assert r.status_code == 200
    body = r.json()
    assert body["keywords"] == ["Python"]
    assert body["inferences"][0]["claim"] == "Experience with Kubernetes"
    assert set(body["inferences"][0].keys()) == {
        "id",
        "claim",
        "rationale",
        "experienceId",
    }

    # confirm (reject the inference so the guardrail stays satisfiable)
    r = client.post("/api/confirm-inferences", json={"approvedIds": []})
    assert r.status_code == 204


def test_confirm_writes_edited_claim(client):
    """A user-edited claim (not the original) is persisted as a user-confirmed
    bullet on the target experience."""
    client.post(
        "/api/upload",
        files={"file": ("cv.pdf", io.BytesIO(_HANDWRITTEN_PDF), "application/pdf")},
    )
    client.post("/api/extract")
    inf = client.post(
        "/api/tailor", json={"posting": "Python and Kubernetes role"}
    ).json()["inferences"][0]
    assert inf["claim"] == "Experience with Kubernetes"  # the LLM-proposed text

    edited = "Ran a 40-node Kubernetes cluster in production"
    r = client.post(
        "/api/confirm-inferences",
        json={
            "approved": [
                {
                    "id": inf["id"],
                    "claim": edited,
                    "experienceId": inf["experienceId"],
                }
            ]
        },
    )
    assert r.status_code == 204, r.text

    truth = client.get("/api/truth").json()
    target = next(
        e for e in truth["experiences"] if e["id"] == inf["experienceId"]
    )
    added = [b for b in target["bullets"] if b["source"] == "user-confirmed"]
    assert [b["value"] for b in added] == [edited]  # edited text, not original


def test_confirm_legacy_approved_ids_writes_original(client):
    """The deprecated approvedIds path still writes each id's original draft
    claim verbatim."""
    client.post(
        "/api/upload",
        files={"file": ("cv.pdf", io.BytesIO(_HANDWRITTEN_PDF), "application/pdf")},
    )
    client.post("/api/extract")
    inf = client.post(
        "/api/tailor", json={"posting": "Python and Kubernetes role"}
    ).json()["inferences"][0]

    r = client.post("/api/confirm-inferences", json={"approvedIds": [inf["id"]]})
    assert r.status_code == 204, r.text

    truth = client.get("/api/truth").json()
    target = next(
        e for e in truth["experiences"] if e["id"] == inf["experienceId"]
    )
    added = [b for b in target["bullets"] if b["source"] == "user-confirmed"]
    assert [b["value"] for b in added] == ["Experience with Kubernetes"]

    # render — guardrail passes (draft is truth-only); PDF/DOCX may be unavailable
    r = client.post("/api/render")
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        rr = r.json()
        assert rr["blocked"] is False
        assert "atsWarnings" in rr
        assert "pdfUrl" in rr and "docxUrl" in rr


def test_render_blocked_when_draft_has_non_truth_token(client):
    # Seed truth + a draft whose bullet references a fabricated token.
    from truth import save
    from truth.model import Experience, Skill, Truth
    import tailor as te
    from tailor.model import Draft, DraftExperience

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
                    bullets=[],
                )
            ],
            skills=[Skill(id="sk-python", value="Python", source="linkedin-pdf")],
        )
    )
    te.save_draft(
        Draft(
            experiences=[
                DraftExperience(
                    source_id="exp-1",
                    role="Engineer",
                    company="Acme",
                    dates="2020 – 2023",
                    bullets=["Expert in Python and Kubernetes"],
                )
            ],
            skills=["Python"],
            keywords=["Python"],
        )
    )
    r = client.post("/api/render")
    assert r.status_code == 200
    rr = r.json()
    assert rr["blocked"] is True
    assert "kubernetes" in rr["unverifiable"]
    # The whole flagged bullet is surfaced for per-claim approve/deny.
    assert rr["blockedClaims"][0]["experienceId"] == "exp-1"
    assert "kubernetes" in rr["blockedClaims"][0]["tokens"]


def _seed_truth_with_summary(summary: str) -> None:
    """Truth with one experience/skill and a profile summary, plus a matching
    truth-only draft so /render exercises only the summary scope."""
    from truth import save
    from truth.model import Experience, Profile, Skill, Truth
    import tailor as te
    from tailor.model import Draft, DraftExperience

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
                    bullets=[],
                )
            ],
            skills=[Skill(id="sk-python", value="Python", source="linkedin-pdf")],
            profile=Profile(
                name="Jane Doe",
                email="jane@example.com",
                phone="+1 555 0100",
                summary=summary,
            ),
        )
    )
    te.save_draft(
        Draft(
            experiences=[
                DraftExperience(
                    source_id="exp-1",
                    role="Engineer",
                    company="Acme",
                    dates="2020 – 2023",
                    bullets=[],  # draft bullets are truth-only, so only the summary scope can trip
                )
            ],
            skills=["Python"],
            keywords=["Python"],
        )
    )


def test_render_blocked_when_summary_has_non_truth_token(client):
    # Summary claims Kubernetes, which appears in no experience/bullet/skill.
    _seed_truth_with_summary("Engineer at Acme with deep Kubernetes expertise")
    r = client.post("/api/render")
    assert r.status_code == 200
    rr = r.json()
    assert rr["blocked"] is True
    assert "kubernetes" in rr["unverifiable"]
    # The summary trips its OWN scope, traceable back as experienceId 'summary'.
    summary_claims = [
        c for c in rr["blockedClaims"] if c["experienceId"] == "summary"
    ]
    assert summary_claims, rr["blockedClaims"]
    assert "kubernetes" in summary_claims[0]["tokens"]


def test_render_allows_summary_drawn_from_truth(client):
    # Summary uses only tokens present in truth (Engineer/Acme/Python) -> passes
    # the guardrail. PDF/DOCX backend may be unavailable, hence 200-or-500.
    _seed_truth_with_summary("Engineer at Acme, strong in Python")
    r = client.post("/api/render")
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        assert r.json()["blocked"] is False


def test_render_summary_contact_fields_never_block(client):
    # Email/phone/name are identity, exempt from the guardrail: a summary that is
    # empty must never surface those tokens as unverifiable.
    _seed_truth_with_summary("")  # no summary claim at all
    r = client.post("/api/render")
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        rr = r.json()
        assert rr["blocked"] is False
        # sanity: contact tokens never leak into a scope
        assert "jane" not in rr.get("unverifiable", [])


def test_truth_put_get_round_trips_profile(client):
    body = {
        "experiences": [],
        "education": [],
        "skills": [],
        "profile": {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "+1 555 0100",
            "location": "Berlin",
            "links": [{"label": "LinkedIn", "url": "https://li/jane"}],
            "summary": "Backend engineer",
        },
    }
    r = client.put("/api/truth", json=body)
    assert r.status_code == 204, r.text

    got = client.get("/api/truth").json()["profile"]
    assert got == body["profile"]  # camelCase, intact


def test_truth_put_persists_summary_edit(client):
    base = {"experiences": [], "education": [], "skills": []}
    client.put("/api/truth", json={**base, "profile": {"summary": "First"}})
    client.put("/api/truth", json={**base, "profile": {"summary": "Second"}})
    assert client.get("/api/truth").json()["profile"]["summary"] == "Second"
