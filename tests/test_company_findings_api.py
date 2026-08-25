"""Company findings API: POST/GET/PATCH /api/company-findings."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _create(client, **overrides):
    body = {
        "company": "Acme Co",
        "claim": "employer_rating",
        "value": "4.5",
        "sourceUrl": "https://a.example/x",
        "sourceClass": "press",
        "asOf": "",
        "note": "",
    }
    body.update(overrides)
    return client.post("/api/company-findings", json=body)


def test_create_company_finding(client):
    r = _create(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"]
    assert body["company"] == "Acme Co"
    assert body["recordedBy"] == "operator"


def test_list_company_findings_newest_first(client):
    _create(client, value="4.5")
    _create(client, claim="employment_entity", value="Acme Ireland Ltd", sourceClass="company_statement")
    r = client.get("/api/company-findings")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert items[0]["observedAt"] >= items[1]["observedAt"]


def test_list_company_findings_for_company(client):
    _create(client, company="Acme Co")
    _create(client, company="Beta Inc", sourceUrl="https://b.example/z")
    r = client.get("/api/company-findings/Acme Co")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["company"] == "Acme Co"


def test_contradictions_route_resolves_ahead_of_company_route(client):
    _create(client, value="4.5", sourceClass="press")
    _create(client, value="3.0", sourceClass="review_site")
    r = client.get("/api/company-findings/contradictions")
    assert r.status_code == 200
    groups = r.json()
    assert len(groups) == 1
    assert groups[0]["claim"] == "employer_rating"

    r2 = client.get("/api/company-findings/contradictions?company=Acme Co")
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_create_rejects_invalid_source_class(client):
    r = _create(client, sourceClass="rumor")
    assert r.status_code == 422


def test_create_rejects_empty_source_url(client):
    r = _create(client, sourceUrl="")
    assert r.status_code == 422


def test_patch_unknown_finding_404s(client):
    r = client.patch("/api/company-findings/does-not-exist", json={"resolution": "accepted"})
    assert r.status_code == 404


def test_patch_resolves_but_cannot_change_factual_fields(client):
    created = _create(client, value="4.5", sourceClass="press").json()
    finding_id = created["id"]
    r = client.patch(
        f"/api/company-findings/{finding_id}",
        json={
            "resolution": "accepted",
            "note": "confirmed by operator",
            "value": "999",
            "sourceUrl": "https://tampered.example",
            "sourceClass": "audited_accounts",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resolution"] == "accepted"
    assert body["resolutionNote"] == "confirmed by operator"
    # Extra fields in the body are ignored by CompanyFindingResolve's shape.
    assert body["value"] == "4.5"
    assert body["sourceUrl"] == "https://a.example/x"
    assert body["sourceClass"] == "press"
