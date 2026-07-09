"""Persisted profile: /api/upload stores the raw PDF; /api/profile reports it."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from api.main import app

_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]"
    b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\n"
    b"BT /F1 12 Tf 20 100 Td (Profile text) Tj ET\n"
    b"endstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R/Size 6>>\nstartxref\n0\n%%EOF"
)


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_profile_absent_then_present(client):
    assert client.get("/api/profile").json()["hasProfile"] is False
    r = client.post(
        "/api/upload",
        files={"file": ("cv.pdf", io.BytesIO(_PDF), "application/pdf")},
    )
    assert r.status_code == 204, r.text
    assert client.get("/api/profile").json()["hasProfile"] is True
