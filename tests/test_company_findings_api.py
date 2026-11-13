"""Company findings API: POST/GET/PATCH /api/company-findings."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from truthcv.adapters.http.main import app


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


def test_create_rejects_claim_outside_enum(client):
    assert _create(client, claim="glassdoor").status_code == 422


def test_create_other_without_label_is_400(client):
    assert _create(client, claim="other").status_code == 400


def test_company_key_present_on_wire(client):
    from truthcv.infra.identity.company import company_identity_key

    body = _create(client, company="RobCo GmbH").json()
    assert body["companyKey"] == company_identity_key("RobCo GmbH")


def test_supersede_via_post(client):
    first = _create(client, value="4.5").json()
    second = _create(client, value="3.0", supersedes=first["id"])
    assert second.status_code == 201, second.text
    assert second.json()["supersedes"] == first["id"]
    assert second.json()["contradicts"] == []
    assert _create(client, value="2.0", supersedes=first["id"]).status_code == 400
    assert client.get("/api/company-findings/contradictions").json() == []


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


@pytest.fixture()
def ordered_clock(monkeypatch):
    """Strictly increasing observed_at stamps, so "newest" is deterministic."""
    from truthcv.domain.companyresearch import store

    ticks = iter(range(10_000))
    monkeypatch.setattr(store, "_now", lambda: f"2026-01-01T00:00:{next(ticks):05d}")


def _companies(client, **params):
    r = client.get("/api/company-findings/companies", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_companies_groups_by_identity_key_with_newest_name(client, ordered_clock):
    _create(client, company="Zalando", value="4.0")
    _create(client, company="Zalando SE", claim="employment_entity", value="Zalando SE")
    body = _companies(client)
    assert body["total"] == 1
    group = body["items"][0]
    assert group["company"] == "Zalando SE"
    assert group["companyKey"] == "zalando"
    # Newest observed first within a group, as the list route serves them.
    assert [f["value"] for f in group["findings"]] == ["Zalando SE", "4.0"]
    assert body["companies"] == ["Zalando SE"]


def test_companies_sorted_case_insensitively(client):
    for name in ("beta Inc", "Acme Co", "Cobalt Ltd"):
        _create(client, company=name)
    body = _companies(client)
    assert [g["company"] for g in body["items"]] == ["Acme Co", "beta Inc", "Cobalt Ltd"]


def test_companies_paging_clamps_and_echoes(client):
    for name in ("Acme Co", "Beta Inc", "Cobalt Ltd"):
        _create(client, company=name)
    page = _companies(client, limit=2, offset=1)
    assert [g["company"] for g in page["items"]] == ["Beta Inc", "Cobalt Ltd"]
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 1)
    low = _companies(client, limit=0, offset=-5)
    assert (low["limit"], low["offset"], len(low["items"])) == (1, 0, 1)
    assert _companies(client, limit=500)["limit"] == 200
    assert _companies(client)["limit"] == 50


def test_companies_search_name_and_value_with_unfiltered_names(client):
    _create(client, company="Acme Co", value="4.5")
    _create(client, company="Beta Inc", claim="employment_entity", value="Beta Holdings BV")
    by_name = _companies(client, q="  ACME ")
    assert [g["company"] for g in by_name["items"]] == ["Acme Co"]
    assert by_name["total"] == 1
    assert by_name["companies"] == ["Acme Co", "Beta Inc"]
    by_value = _companies(client, q="holdings")
    assert [g["company"] for g in by_value["items"]] == ["Beta Inc"]
    assert _companies(client, q="   ")["total"] == 2


def test_companies_needs_review_filter(client):
    _create(client, company="Acme Co", value="4.5", sourceClass="press")
    _create(client, company="Acme Co", value="3.0", sourceClass="review_site")
    _create(client, company="Beta Inc", value="4.0")
    every = _companies(client)
    assert {g["company"]: g["needsReview"] for g in every["items"]} == {
        "Acme Co": True,
        "Beta Inc": False,
    }
    flagged = _companies(client, needs_review="true")
    assert [g["company"] for g in flagged["items"]] == ["Acme Co"]
    assert flagged["total"] == 1
    assert flagged["companies"] == ["Acme Co", "Beta Inc"]


def test_companies_route_not_captured_as_company(client):
    _create(client, company="companies")
    body = _companies(client)
    assert isinstance(body, dict)
    assert body["items"][0]["company"] == "companies"
