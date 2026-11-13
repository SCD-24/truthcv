"""Job Screening API: POST/GET/DELETE /api/screenings, GET /api/cooldown, and
GET/PUT /api/profile/answers (round-trip incl. canonical_cv_asset_id
preservation on partial PUT)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from truthcv.adapters.http.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_applied_route_409s_when_another_record_for_the_posting_is_applied(client):
    from truthcv.domain.screening import store

    url = "https://acme.example/jobs/dup-applied"
    fields = {"company": "Acme", "role": "Engineer", "url": url, "verdict": "rejected"}
    a, _ = store.create_or_get({**fields, "profile": "A"})
    b, _ = store.create_or_get({**fields, "profile": "B"})
    store.set_approval(a.id, "applied")
    r = client.post(f"/api/screenings/{b.id}/applied")
    assert r.status_code == 409
    assert "already been applied" in r.json()["detail"]


def test_applied_route_409s_with_blocklist_message_for_blocked_company(client, monkeypatch):
    from truthcv.domain.agentconfig.store import AgentConfig
    from truthcv.domain.screening import store

    s, _ = store.create_or_get({"company": "Zalando SE", "role": "Engineer", "verdict": "deferred"})
    monkeypatch.setattr(store, "_agent_config_load", lambda: AgentConfig(blocked_companies=["Zalando"]))
    r = client.post(f"/api/screenings/{s.id}/applied")
    assert r.status_code == 409
    assert r.json()["detail"] == "Zalando SE is on the blocklist."
    assert store.get(s.id).approval != "applied"


# --- POST/GET/DELETE screenings -------------------------------------------------

def test_create_list_delete_screening(client):
    r = client.post(
        "/api/screenings",
        json={
            "company": "Acme",
            "role": "Engineer",
            "url": "https://acme.example/jobs/1",
            "screenedDate": "2026-07-01",
            "verdict": "rejected",
            "failingCriterion": "salary",
            "reason": "Below floor.",
            "cooldownExpires": "2026-10-01T00:00:00+00:00",
            "source": "manual",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"]
    assert body["company"] == "Acme"
    assert body["role"] == "Engineer"
    assert body["url"] == "https://acme.example/jobs/1"
    assert body["screenedDate"] == "2026-07-01"
    assert body["verdict"] == "rejected"
    # Rejected criteria are normalized to a category key on write.
    assert body["failingCriterion"] == "salary_floor"
    assert body["reason"] == "Below floor."
    assert body["cooldownExpires"] == "2026-10-01T00:00:00+00:00"
    assert body["source"] == "manual"
    assert body["createdAt"]
    assert body["updatedAt"]
    screening_id = body["id"]

    # List includes it, and preserves the same fields round-tripped from the
    # POST — not just the id.
    r = client.get("/api/screenings")
    assert r.status_code == 200
    listed = next(s for s in r.json() if s["id"] == screening_id)
    assert listed["url"] == "https://acme.example/jobs/1"
    assert listed["screenedDate"] == "2026-07-01"
    assert listed["verdict"] == "rejected"
    assert listed["reason"] == "Below floor."
    assert listed["cooldownExpires"] == "2026-10-01T00:00:00+00:00"

    # Delete.
    assert client.delete(f"/api/screenings/{screening_id}").status_code == 204

    # No longer listed.
    r = client.get("/api/screenings")
    assert all(s["id"] != screening_id for s in r.json())


def test_create_screening_normalizes_messy_role(client):
    """Whitespace in a manually-submitted role is normalized on creation."""
    r = client.post(
        "/api/screenings",
        json={
            "company": "Acme",
            "role": "Senior  Backend\nEngineer",
            "url": "https://acme.example/jobs/2",
            "verdict": "rejected",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "Senior Backend Engineer"


def test_create_screening_without_role_still_succeeds(client):
    """role stays optional on this route — the manual/import path (e.g.
    scripts/migrate_jobs_history.py) must keep working with no role."""
    r = client.post(
        "/api/screenings",
        json={
            "company": "Acme",
            "url": "https://acme.example/jobs/3",
            "verdict": "rejected",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == ""


def test_create_screening_with_blank_company_is_rejected(client):
    r = client.post(
        "/api/screenings",
        json={"company": "   ", "url": "https://acme.example/jobs/9", "verdict": "rejected"},
    )
    assert r.status_code == 422, r.text


def test_create_screening_with_placeholder_company_is_rejected(client):
    r = client.post(
        "/api/screenings",
        json={"company": "Unknown", "url": "https://acme.example/jobs/9", "verdict": "rejected"},
    )
    assert r.status_code == 422, r.text


def test_create_screening_without_verdict_is_rejected(client):
    r = client.post(
        "/api/screenings",
        json={"company": "Acme", "url": "https://acme.example/jobs/9"},
    )
    assert r.status_code == 422, r.text


def test_create_screening_with_unknown_verdict_is_rejected(client):
    r = client.post(
        "/api/screenings",
        json={"company": "Acme", "url": "https://acme.example/jobs/9", "verdict": "maybe"},
    )
    assert r.status_code == 422, r.text


def test_create_screening_rejected_verdict_with_empty_posting_text_still_accepted(client):
    """The posting_text gate only applies to a queueing (passed/deferred)
    verdict — a rejected verdict is exempt, matching record_screening."""
    r = client.post(
        "/api/screenings",
        json={"company": "Acme", "url": "https://acme.example/jobs/9", "verdict": "rejected"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["postingText"] == ""


def test_create_screening_passed_verdict_without_posting_text_is_rejected(client):
    r = client.post(
        "/api/screenings",
        json={"company": "Acme", "url": "https://acme.example/jobs/9", "verdict": "passed"},
    )
    assert r.status_code == 422, r.text


def test_get_screenings_returns_criteria_evidence_fields(client):
    """GET /api/screenings surfaces profile/remoteArrangement/
    languageRequirement for a record that carries them — the approval queue
    needs the evidence trail, not just the verdict."""
    import truthcv.domain.screening.store as screening_store

    screening_store.create(
        {
            "company": "Acme",
            "role": "Engineer",
            "url": "https://acme.example/jobs/criteria-1",
            "verdict": "rejected",
            "profile": "default",
            "remote_arrangement": "on_site",
            "language_requirement": "German",
        }
    )

    r = client.get("/api/screenings")
    assert r.status_code == 200
    listed = next(s for s in r.json() if s["url"] == "https://acme.example/jobs/criteria-1")
    assert listed["profile"] == "default"
    assert listed["remoteArrangement"] == "on_site"
    assert listed["languageRequirement"] == "german"


def test_create_screening_queueing_verdict_stays_ungated(client):
    """POST /api/screenings is deliberately NOT gated on profile/
    remote_arrangement — that gate applies only to the agent's
    record_screening tool. The operator may record whatever they judge."""
    r = client.post(
        "/api/screenings",
        json={
            "company": "Acme",
            "role": "Engineer",
            "url": "https://acme.example/jobs/10",
            "verdict": "passed",
            "postingText": "We are hiring an Engineer. " * 10,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["profile"] == ""
    assert r.json()["remoteArrangement"] == ""


def test_create_list_screening_carries_posting_text_and_posted_date(client):
    # Regression test: ScreeningModel omitted posting_text/posted_date, so
    # Pydantic's extra="ignore" silently dropped both from the response even
    # though Screening.EDITABLE stores them.
    r = client.post(
        "/api/screenings",
        json={
            "company": "Acme",
            "role": "Engineer",
            "url": "https://acme.example/jobs/1",
            "verdict": "passed",
            "postingText": "We are hiring an Engineer. " * 10,
            "postedDate": "2026-07-01",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["postingText"] == ("We are hiring an Engineer. " * 10).strip()
    assert body["postedDate"] == "2026-07-01"
    screening_id = body["id"]

    r = client.get("/api/screenings")
    assert r.status_code == 200
    listed = next(s for s in r.json() if s["id"] == screening_id)
    assert listed["postingText"] == ("We are hiring an Engineer. " * 10).strip()
    assert listed["postedDate"] == "2026-07-01"


def test_list_screenings_most_recent_first(client):
    first = client.post(
        "/api/screenings",
        json={
            "company": "First",
            "url": "https://acme.example/jobs/1",
            "verdict": "passed",
            "postingText": "We are hiring for this role at First. " * 6,
        },
    ).json()
    second = client.post(
        "/api/screenings",
        json={
            "company": "Second",
            "url": "https://acme.example/jobs/2",
            "verdict": "passed",
            "postingText": "We are hiring for this role at Second. " * 6,
        },
    ).json()

    listed = client.get("/api/screenings").json()
    ids = [s["id"] for s in listed]
    assert ids.index(second["id"]) < ids.index(first["id"])


# --- GET screenings/rejected ----------------------------------------------------

def _post_agent_rejection(client, company, criterion=""):
    r = client.post(
        "/api/screenings",
        json={
            "company": company,
            "role": "Engineer",
            "url": f"https://{company.lower()}.example/jobs/1",
            "verdict": "rejected",
            "failingCriterion": criterion,
            "reason": "Does not fit.",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _store_operator_rejection(company):
    from truthcv.domain.screening import store

    rec, _ = store.create_or_get({
        "company": company,
        "role": "Engineer",
        "url": f"https://{company.lower()}.example/jobs/2",
        "verdict": "passed",
        "posting_text": "We are hiring for this role. " * 6,
    })
    store.set_approval(rec.id, "rejected")
    return rec


def test_rejected_route_page_shape_and_rejected_by_labels(client):
    agent = _post_agent_rejection(client, "Acme", "salary_floor")
    operator = _store_operator_rejection("Beta")
    r = client.get("/api/screenings/rejected")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"items", "total", "limit", "offset", "categories"}
    assert (body["total"], body["limit"], body["offset"]) == (2, 50, 0)
    assert body["categories"] == [
        {"key": "salary_floor", "count": 1},
        {"key": "none", "count": 1},
    ]
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[agent["id"]]["rejectedBy"] == "agent"
    assert by_id[agent["id"]]["failingCriterion"] == "salary_floor"
    assert by_id[agent["id"]]["createdAt"]
    assert by_id[operator.id]["rejectedBy"] == "operator"


def test_rejected_route_pages_with_total_and_echoes_clamped_params(client):
    for n in range(3):
        _post_agent_rejection(client, f"Co{n}")
    page = client.get("/api/screenings/rejected", params={"limit": 2, "offset": 1}).json()
    assert (len(page["items"]), page["total"], page["limit"], page["offset"]) == (2, 3, 2, 1)
    clamped = client.get(
        "/api/screenings/rejected", params={"limit": 0, "offset": -5}
    ).json()
    assert (len(clamped["items"]), clamped["limit"], clamped["offset"]) == (1, 1, 0)


def test_rejected_route_category_filter_keeps_counts_for_all_categories(client):
    _post_agent_rejection(client, "Acme", "salary_floor")
    _post_agent_rejection(client, "Beta", "role_fit")
    body = client.get("/api/screenings/rejected", params={"category": "role_fit"}).json()
    assert body["total"] == 1
    assert [item["failingCriterion"] for item in body["items"]] == ["role_fit"]
    assert {c["key"]: c["count"] for c in body["categories"]} == {
        "salary_floor": 1,
        "role_fit": 1,
    }
    unknown = client.get("/api/screenings/rejected", params={"category": "bogus"}).json()
    assert (unknown["items"], unknown["total"]) == ([], 0)


def test_list_screenings_stays_an_unpaged_array_beside_rejected_route(client):
    for n in range(3):
        _post_agent_rejection(client, f"Co{n}")
    listed = client.get("/api/screenings").json()
    assert isinstance(listed, list) and len(listed) == 3
    assert len(client.get("/api/screenings/rejected", params={"limit": 2}).json()["items"]) == 2


def test_delete_unknown_screening_returns_404(client):
    r = client.delete("/api/screenings/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"detail": "Screening not found."}


def test_delete_already_deleted_screening_returns_404(client):
    screening_id = client.post(
        "/api/screenings",
        json={
            "company": "Acme",
            "url": "https://acme.example/jobs/1",
            "verdict": "passed",
            "postingText": "We are hiring an Engineer at Acme. " * 6,
        },
    ).json()["id"]
    assert client.delete(f"/api/screenings/{screening_id}").status_code == 204
    r = client.delete(f"/api/screenings/{screening_id}")
    assert r.status_code == 404
    assert r.json() == {"detail": "Screening not found."}


# --- POST /api/screenings/deletions (bulk delete) --------------------------------

def test_bulk_delete_removes_several_screenings(client):
    a = client.post(
        "/api/screenings",
        json={"company": "Acme", "url": "https://acme.example/jobs/1", "verdict": "rejected"},
    ).json()
    b = client.post(
        "/api/screenings",
        json={"company": "Beta", "url": "https://acme.example/jobs/2", "verdict": "rejected"},
    ).json()

    r = client.post("/api/screenings/deletions", json={"ids": [a["id"], b["id"]]})
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert {(x["id"], x["ok"]) for x in results} == {(a["id"], True), (b["id"], True)}

    remaining = {s["id"] for s in client.get("/api/screenings").json()}
    assert a["id"] not in remaining
    assert b["id"] not in remaining


def test_bulk_delete_empty_ids_returns_empty_results(client):
    r = client.post("/api/screenings/deletions", json={"ids": []})
    assert r.status_code == 200
    assert r.json() == {"results": []}


def test_bulk_delete_mixed_known_and_unknown_ids(client):
    a = client.post(
        "/api/screenings",
        json={"company": "Acme", "url": "https://acme.example/jobs/1", "verdict": "rejected"},
    ).json()

    r = client.post(
        "/api/screenings/deletions", json={"ids": [a["id"], "does-not-exist"]}
    )
    assert r.status_code == 200
    results = {x["id"]: x["ok"] for x in r.json()["results"]}
    assert results == {a["id"]: True, "does-not-exist": False}


def test_bulk_delete_route_resolves_not_bound_as_screening_id(client):
    # A POST to /screenings/deletions must hit bulk_delete_screenings, not be
    # swallowed by /screenings/{screening_id} routes (which wouldn't match
    # POST anyway, but this pins the route ordering/contract regardless).
    r = client.post("/api/screenings/deletions", json={"ids": []})
    assert r.status_code == 200
    assert "results" in r.json()


# --- url is mandatory on create -------------------------------------------------

def test_create_screening_without_url_is_rejected(client):
    r = client.post(
        "/api/screenings",
        json={"company": "Acme", "role": "Engineer", "verdict": "passed"},
    )
    assert r.status_code == 422, r.text


def test_create_screening_with_empty_url_is_rejected(client):
    r = client.post(
        "/api/screenings",
        json={"company": "Acme", "role": "Engineer", "url": "", "verdict": "passed"},
    )
    assert r.status_code == 422, r.text


def test_create_screening_with_schemeless_url_is_rejected(client):
    r = client.post(
        "/api/screenings",
        json={
            "company": "Acme",
            "role": "Engineer",
            "url": "acme.example/jobs/1",
            "verdict": "passed",
        },
    )
    assert r.status_code == 422, r.text


# --- GET /api/cooldown -----------------------------------------------------------

def test_cooldown_from_screening_data_source(client):
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    client.post(
        "/api/screenings",
        json={
            "company": "Acme",
            "role": "Engineer",
            "url": "https://acme.example/jobs/1",
            "verdict": "rejected",
            "cooldownExpires": future,
        },
    )
    r = client.get("/api/cooldown", params={"company": "Acme", "role": "Engineer"})
    assert r.status_code == 200
    body = r.json()
    assert body["inCooldown"] is True
    assert body["expires"] == future


def test_cooldown_role_mismatch_not_in_cooldown(client):
    """A screening for the same company but a different role must not put the
    queried role in cooldown."""
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    client.post(
        "/api/screenings",
        json={
            "company": "Acme",
            "role": "Engineer",
            "url": "https://acme.example/jobs/1",
            "verdict": "rejected",
            "cooldownExpires": future,
        },
    )
    r = client.get("/api/cooldown", params={"company": "Acme", "role": "Designer"})
    assert r.status_code == 200
    body = r.json()
    assert body["inCooldown"] is False
    assert body["expires"] is None


def test_cooldown_from_application_data_source(client, monkeypatch):
    # The Application wire schema has no `role` field, so applications are
    # matched by company alone here (unlike the screening source above).
    monkeypatch.setenv("APPLICATION_COOLDOWN_DAYS", "90")
    recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
    client.post(
        "/api/applications",
        json={"company": "Acme", "applicationDate": recent_date},
    )
    r = client.get("/api/cooldown", params={"company": "Acme"})
    assert r.status_code == 200
    assert r.json()["inCooldown"] is True


def test_cooldown_prefers_later_expiry_across_both_sources(client, monkeypatch):
    monkeypatch.setenv("APPLICATION_COOLDOWN_DAYS", "90")

    # Screening's own cooldown expires soon.
    near = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    client.post(
        "/api/screenings",
        json={"company": "Acme", "url": "https://acme.example/jobs/1", "verdict": "rejected", "cooldownExpires": near},
    )

    # Application-derived expiry lands further out.
    app_date = (datetime.now(timezone.utc) - timedelta(days=10)).date()
    client.post(
        "/api/applications",
        json={"company": "Acme", "applicationDate": app_date.isoformat()},
    )
    expected_far_expiry = (
        datetime(app_date.year, app_date.month, app_date.day, tzinfo=timezone.utc)
        + timedelta(days=90)
    )

    r = client.get("/api/cooldown", params={"company": "Acme"})
    assert r.status_code == 200
    body = r.json()
    assert body["inCooldown"] is True
    assert datetime.fromisoformat(body["expires"]) == expected_far_expiry
    assert datetime.fromisoformat(body["expires"]) > datetime.fromisoformat(near)


def test_cooldown_no_match_reports_not_in_cooldown(client):
    r = client.get("/api/cooldown", params={"company": "Nobody Corp"})
    assert r.status_code == 200
    body = r.json()
    assert body["inCooldown"] is False
    assert body["expires"] is None


def test_cooldown_reports_blocking_window(client, data_dir, monkeypatch):
    """GET /api/cooldown names the window: role-matched vs company-only."""
    from truthcv.domain.agentconfig import store as agent_config_store

    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    cfg = agent_config_store.load()
    cfg.cooldown_days = 30
    agent_config_store.save(cfg)

    recent = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
    client.post("/api/applications", json={"company": "Acme", "role": "Engineer", "applicationDate": recent})

    role_match = client.get("/api/cooldown", params={"company": "Acme", "role": "Engineer"})
    assert role_match.json()["window"] == "same_role"

    company_only = client.get("/api/cooldown", params={"company": "Acme"})
    assert company_only.json()["window"] == "same_company"


def test_cooldown_window_none_when_clear_or_blocklisted(client, data_dir):
    from truthcv.domain.agentconfig import store as agent_config_store

    cfg = agent_config_store.load()
    cfg.blocked_companies = ["BlockCo"]
    agent_config_store.save(cfg)

    blocked = client.get("/api/cooldown", params={"company": "BlockCo"})
    assert blocked.json()["blocked"] is True
    assert blocked.json()["window"] is None

    clear = client.get("/api/cooldown", params={"company": "QuietCo"})
    assert clear.json()["inCooldown"] is False
    assert clear.json()["window"] is None


def test_answers_wire_carries_work_authorisation_note(client, data_dir):
    """workAuthorisationNote round-trips; the legacy field still does too."""
    r = client.put(
        "/api/profile/answers",
        json={
            "workAuthorisationNote": "EU citizen, no sponsorship needed",
            "authorizedNonGermanCountry": "legacy value",
        },
    )
    assert r.status_code == 200
    assert r.json()["workAuthorisationNote"] == "EU citizen, no sponsorship needed"
    assert r.json()["authorizedNonGermanCountry"] == "legacy value"

    got = client.get("/api/profile/answers").json()
    assert got["workAuthorisationNote"] == "EU citizen, no sponsorship needed"
    # The legacy field stays present on the wire for un-migrated clients.
    assert "authorizedNonGermanCountry" in got
    assert got["authorizedNonGermanCountry"] == "legacy value"


# --- GET/PUT /api/profile/answers -------------------------------------------------

def test_get_answers_returns_defaults(client):
    r = client.get("/api/profile/answers")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == ""
    assert body["canonicalCvAssetId"] is None


def test_put_answers_round_trips(client):
    r = client.put(
        "/api/profile/answers",
        json={"phone": "+1 555 0100", "canonicalCvAssetId": "canonical_cv.pdf"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] == "+1 555 0100"
    assert body["canonicalCvAssetId"] == "canonical_cv.pdf"

    # GET reflects the same persisted values.
    r = client.get("/api/profile/answers")
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] == "+1 555 0100"
    assert body["canonicalCvAssetId"] == "canonical_cv.pdf"


def test_put_answers_partial_preserves_canonical_cv_asset_id(client):
    """A later partial PUT that omits canonicalCvAssetId must not clobber it —
    only the fields actually sent in the body are merged onto the stored
    answers."""
    client.put(
        "/api/profile/answers",
        json={"phone": "+1 555 0100", "canonicalCvAssetId": "canonical_cv.pdf"},
    )

    r = client.put("/api/profile/answers", json={"name": "Jane Doe"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Jane Doe"
    assert body["phone"] == "+1 555 0100"  # untouched by the partial PUT
    assert body["canonicalCvAssetId"] == "canonical_cv.pdf"  # preserved

    # And persisted, not just returned.
    r = client.get("/api/profile/answers")
    body = r.json()
    assert body["canonicalCvAssetId"] == "canonical_cv.pdf"
    assert body["phone"] == "+1 555 0100"


def test_put_answers_partial_applies_empty_string_but_preserves_omitted_field(client):
    """A field explicitly sent as "" is a real value and must be applied
    (clearing the prior value), which is distinct from a field that is
    omitted entirely from the body and therefore left untouched."""
    client.put(
        "/api/profile/answers",
        json={"phone": "+1 555 0100", "canonicalCvAssetId": "canonical_cv.pdf"},
    )

    r = client.put("/api/profile/answers", json={"phone": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] == ""  # explicit "" is applied, clearing the prior value
    assert body["canonicalCvAssetId"] == "canonical_cv.pdf"  # omitted, preserved

    # And persisted, not just returned.
    r = client.get("/api/profile/answers")
    body = r.json()
    assert body["phone"] == ""
    assert body["canonicalCvAssetId"] == "canonical_cv.pdf"


def _two_rejected_for_one_url():
    from truthcv.domain.screening import store

    base = {"company": "Acme", "role": "Eng", "url": "https://acme.example/jobs/9",
            "verdict": "rejected"}
    a, _ = store.create_or_get({**base, "profile": "A"})
    b, _ = store.create_or_get({**base, "profile": "B"})
    return a, b


def test_patch_second_approval_for_one_posting_is_409(client):
    a, b = _two_rejected_for_one_url()
    assert client.patch(f"/api/screenings/{a.id}", json={"approval": "approved"}).status_code == 200
    r = client.patch(f"/api/screenings/{b.id}", json={"approval": "approved"})
    assert r.status_code == 409, r.text
    assert a.id in r.json()["detail"]


def test_bulk_approval_reports_conflict_without_aborting(client):
    a, b = _two_rejected_for_one_url()
    body = client.patch(
        "/api/screenings/approvals", json={"ids": [a.id, b.id], "approval": "approved"}
    ).json()
    assert body["results"] == [{"id": a.id, "ok": True}, {"id": b.id, "ok": False}]


# --- Blocklist: a blocked company never reaches the approval queue ------------

_BLOCKED_POSTING_TEXT = "We are hiring an Engineer. " * 10


def _block_and_enable_profile(*blocked):
    """Save an agent config blocking ``blocked`` with one enabled profile."""
    from truthcv.domain.agentconfig import store as agent_config_store

    cfg = agent_config_store.load()
    cfg.blocked_companies = list(blocked)
    cfg.profiles = [agent_config_store.JobProfile(name="default", enabled=True)]
    agent_config_store.save(cfg)


def _record_verdict(company, verdict, url, **extra):
    import truthcv.services.screenings as screenings_service

    screening, _ = screenings_service.record_screening_verdict(
        url=url,
        role="Engineer",
        company=company,
        verdict=verdict,
        reason="Looks good.",
        posting_text=_BLOCKED_POSTING_TEXT,
        profile="default",
        remote_arrangement="remote",
        **extra,
    )
    return screening


def _assert_blocked_rejection(verdict, failing_criterion, reason, approval):
    from truthcv.services.screenings import (
        COMPANY_BLOCKED_CRITERION,
        COMPANY_BLOCKED_REASON_PREFIX,
    )

    assert verdict == "rejected"
    assert failing_criterion == COMPANY_BLOCKED_CRITERION
    assert reason == f"{COMPANY_BLOCKED_REASON_PREFIX}Looks good."
    assert approval != "pending"


@pytest.mark.parametrize("verdict", ["passed", "deferred"])
def test_record_screening_verdict_blocked_company_is_rejected_not_queued(verdict):
    _block_and_enable_profile("Zalando SE")
    s = _record_verdict("Zalando SE", verdict, f"https://zalando.example/jobs/{verdict}")
    _assert_blocked_rejection(s.verdict, s.failing_criterion, s.reason, s.approval)


def test_record_screening_verdict_blocked_company_with_blocker_is_rejected():
    _block_and_enable_profile("Zalando SE")
    s = _record_verdict(
        "Zalando SE", "passed", "https://zalando.example/jobs/blocker",
        screening_blocker="unreadable",
    )
    _assert_blocked_rejection(s.verdict, s.failing_criterion, s.reason, s.approval)


@pytest.mark.parametrize("verdict", ["", "passed"])
def test_record_screening_verdict_blocked_company_login_required_not_queued(verdict):
    # login_required queues in the store whatever the verdict, so the
    # blocklist must drop it too, not only downgrade the verdict.
    _block_and_enable_profile("Zalando SE")
    s = _record_verdict(
        "Zalando SE", verdict, f"https://zalando.example/jobs/login-{verdict or 'none'}",
        screening_blocker="login_required",
    )
    _assert_blocked_rejection(s.verdict, s.failing_criterion, s.reason, s.approval)
    assert s.screening_blocker == ""


def test_record_screening_verdict_blocklist_matches_legal_suffix():
    _block_and_enable_profile("Zalando")
    s = _record_verdict("Zalando SE", "deferred", "https://zalando.example/jobs/suffix")
    _assert_blocked_rejection(s.verdict, s.failing_criterion, s.reason, s.approval)


def test_record_screening_verdict_unblocked_company_still_queues():
    _block_and_enable_profile("Zalando")
    s = _record_verdict("Acme", "deferred", "https://acme.example/jobs/unblocked")
    assert s.verdict == "deferred"
    assert s.approval == "pending"


@pytest.mark.parametrize("verdict", ["passed", "deferred"])
def test_create_screening_route_blocked_company_is_rejected_not_queued(client, verdict):
    _block_and_enable_profile("Zalando")
    r = client.post(
        "/api/screenings",
        json={
            "company": "Zalando SE",
            "role": "Engineer",
            "url": f"https://zalando.example/jobs/http-{verdict}",
            "verdict": verdict,
            "reason": "Looks good.",
            "postingText": _BLOCKED_POSTING_TEXT,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    _assert_blocked_rejection(
        body["verdict"], body["failingCriterion"], body["reason"], body["approval"]
    )


def test_create_screening_route_unblocked_company_still_queues(client):
    _block_and_enable_profile("Zalando")
    r = client.post(
        "/api/screenings",
        json={
            "company": "Acme",
            "url": "https://acme.example/jobs/http-unblocked",
            "verdict": "deferred",
            "postingText": _BLOCKED_POSTING_TEXT,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["verdict"] == "deferred"
    assert r.json()["approval"] == "pending"
