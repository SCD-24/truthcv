"""Each call site asks get_provider for its own task name."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from providers.fake import FakeProvider


def test_tailor_resolves_per_subtask(data_dir):
    asked: list[str | None] = []

    def provider_for(task=None):
        asked.append(task)
        return FakeProvider()

    import tailor as tailor_engine
    from truth.model import Truth

    tailor_engine.tailor("posting text", Truth(), provider_for)
    assert asked == ["keywords", "tailor", "infer"]


# A minimal, valid single-page PDF with selectable text, matching the fixture
# used in tests/test_api.py's upload/extract flow.
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


def test_extract_route_passes_task_name(data_dir, monkeypatch):
    asked: list[str | None] = []

    def fake_get_provider(task=None, refresh=False):
        asked.append(task)
        return FakeProvider(
            router=lambda system, messages, schema: {
                "experiences": [],
                "education": [],
                "skills": [],
            }
        )

    import api.routes as routes
    from api.main import app

    monkeypatch.setattr(routes, "get_provider", fake_get_provider)
    client = TestClient(app)
    client.post(
        "/api/upload",
        files={"file": ("cv.pdf", io.BytesIO(_HANDWRITTEN_PDF), "application/pdf")},
    )
    r = client.post("/api/extract")
    assert r.status_code == 200, r.text
    assert "truth_extract" in asked


def test_routes_pass_task_names(data_dir, monkeypatch):
    """The API handlers hand get_provider their task name (patched at the
    api.routes seam, the same one existing tests patch)."""
    asked: list[str | None] = []

    def fake_get_provider(task=None, refresh=False):
        asked.append(task)
        return FakeProvider(
            router=lambda system, messages, schema: {
                "paragraphs": [
                    {"text": "I use Python at Acme Corp.", "claims": ["Python", "Acme Corp"]}
                ]
            }
        )

    import api.routes as routes
    from truth import save
    from truth.model import Experience, Skill, Truth
    from truth.store import data_dir as dd

    monkeypatch.setattr(routes, "get_provider", fake_get_provider)
    save(
        Truth(
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
            education=[],
            skills=[Skill(id="s1", value="Python", source="linkedin-pdf")],
        )
    )
    (dd() / "posting.txt").write_text("Python role at a startup")

    from api.main import app

    client = TestClient(app)
    r = client.post("/api/cover-letter", json={"tone": "Professional", "length": "Short"})
    assert r.status_code in (200, 500), r.text
    assert "cover_letter" in asked
