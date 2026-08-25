"""Approval routes: the operator's surface, unreachable from the agent."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import screening.store as store
from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _deferred(company="Contoso Labs", role="Staff AI Engineer"):
    return store.create({"company": company, "role": role, "verdict": "deferred"})


def test_list_filters_by_approval(client):
    _deferred()
    store.create({"company": "Soylent", "verdict": "rejected"})
    rows = client.get("/api/screenings?approval=pending").json()
    assert [r["company"] for r in rows] == ["Contoso Labs"]


def test_list_unfiltered_returns_everything(client):
    _deferred()
    store.create({"company": "Soylent", "verdict": "rejected"})
    assert len(client.get("/api/screenings").json()) == 2


def test_wire_model_exposes_approval_fields(client):
    _deferred()
    row = client.get("/api/screenings").json()[0]
    assert row["approval"] == "pending"
    assert row["applyAttempts"] == 0
    assert row["applyError"] == ""


def test_patch_sets_approval(client):
    import coverletter.store as letters

    s = _deferred()
    letters.save(s.id, letters.CoverLetterDraft(text="Dear team,"))
    body = client.patch(f"/api/screenings/{s.id}", json={"approval": "approved"}).json()
    assert body["approval"] == "approved"
    assert store.get(s.id).approval == "approved"


def test_patch_unknown_id_404(client):
    assert client.patch("/api/screenings/nope", json={"approval": "approved"}).status_code == 404


def test_patch_bad_value_422(client):
    s = _deferred()
    assert client.patch(f"/api/screenings/{s.id}", json={"approval": "sure"}).status_code == 422


def test_patch_sets_url_only(client):
    s = _deferred()
    body = client.patch(f"/api/screenings/{s.id}", json={"url": "https://x.com/1"}).json()
    assert body["url"] == "https://x.com/1"
    assert body["approval"] == "pending"
    reloaded = store.get(s.id)
    assert reloaded.url == "https://x.com/1"
    assert reloaded.approval == "pending"


def test_patch_sets_url_and_approval(client):
    import coverletter.store as letters

    s = _deferred()
    letters.save(s.id, letters.CoverLetterDraft(text="Dear team,"))
    body = client.patch(
        f"/api/screenings/{s.id}",
        json={"url": "https://x.com/1", "approval": "approved"},
    ).json()
    assert body["url"] == "https://x.com/1"
    assert body["approval"] == "approved"
    reloaded = store.get(s.id)
    assert reloaded.url == "https://x.com/1"
    assert reloaded.approval == "approved"


def test_patch_sets_posting_text(client):
    s = _deferred()
    r = client.patch(
        f"/api/screenings/{s.id}", json={"postingText": "We are hiring an Engineer."}
    )
    assert r.status_code == 200, r.text
    assert r.json()["postingText"] == "We are hiring an Engineer."
    reloaded = store.get(s.id)
    assert reloaded.posting_text == "We are hiring an Engineer."
    assert reloaded.approval == "pending"


def test_patch_empty_body_422(client):
    s = _deferred()
    assert client.patch(f"/api/screenings/{s.id}", json={}).status_code == 422


def test_patch_sets_role_only(client):
    s = _deferred()
    body = client.patch(
        f"/api/screenings/{s.id}", json={"role": "Staff Engineer"}
    ).json()
    assert body["role"] == "Staff Engineer"
    reloaded = store.get(s.id)
    assert reloaded.role == "Staff Engineer"
    assert reloaded.approval == "pending"


def test_patch_role_persists_and_is_visible_on_list(client):
    s = _deferred()
    client.patch(f"/api/screenings/{s.id}", json={"role": "Staff Engineer"})
    rows = client.get("/api/screenings").json()
    assert [r["role"] for r in rows if r["id"] == s.id] == ["Staff Engineer"]


@pytest.mark.parametrize("bad_role", ["   ", "Apply now", "x" * 200])
def test_patch_invalid_role_422_and_unchanged(client, bad_role):
    s = _deferred()
    r = client.patch(f"/api/screenings/{s.id}", json={"role": bad_role})
    assert r.status_code == 422, r.text
    assert store.get(s.id).role == "Staff AI Engineer"


def test_patch_role_unknown_id_404(client):
    assert (
        client.patch("/api/screenings/nope", json={"role": "Staff Engineer"}).status_code
        == 404
    )


def test_patch_role_and_approval_together(client):
    import coverletter.store as letters

    s = _deferred()
    letters.save(s.id, letters.CoverLetterDraft(text="Dear team,"))
    body = client.patch(
        f"/api/screenings/{s.id}",
        json={"role": "Staff Engineer", "approval": "approved"},
    ).json()
    assert body["role"] == "Staff Engineer"
    assert body["approval"] == "approved"
    reloaded = store.get(s.id)
    assert reloaded.role == "Staff Engineer"
    assert reloaded.approval == "approved"


def test_patch_schemeless_url_422(client):
    s = _deferred()
    r = client.patch(f"/api/screenings/{s.id}", json={"url": "acme.example/jobs/1"})
    assert r.status_code == 422, r.text


def test_patch_url_unknown_id_404(client):
    assert client.patch("/api/screenings/nope", json={"url": "https://x.com/1"}).status_code == 404


def test_bulk_patch_reports_per_id(client):
    import coverletter.store as letters

    a, b = _deferred("Contoso Labs"), _deferred("Aperture")
    letters.save(a.id, letters.CoverLetterDraft(text="Dear team,"))
    letters.save(b.id, letters.CoverLetterDraft(text="Dear team,"))
    body = client.patch(
        "/api/screenings/approvals",
        json={"ids": [a.id, b.id, "missing"], "approval": "approved"},
    ).json()
    assert body["results"] == [
        {"id": a.id, "ok": True},
        {"id": b.id, "ok": True},
        {"id": "missing", "ok": False},
    ]
    assert store.get(a.id).approval == "approved"


def test_bulk_route_is_not_shadowed_by_the_id_route(client):
    """PATCH /screenings/approvals must not bind 'approvals' as an id."""
    resp = client.patch("/api/screenings/approvals", json={"ids": [], "approval": "approved"})
    assert resp.status_code == 200
    assert resp.json() == {"results": []}


def test_no_agent_route_writes_approval(client):
    """The agent authenticates only against /api/agent/*. No path under that
    prefix may write approval, and no tool on its surface may either — the
    structural half of "the human approves, the agent never does"."""
    paths = app.openapi()["paths"]
    agent_paths = [p for p in paths if p.startswith("/api/agent")]
    assert agent_paths, "expected some /api/agent routes to exist"
    for path in agent_paths:
        assert "approval" not in path

    # And the approval writers are reachable only outside that prefix.
    approval_paths = [p for p in paths if "approval" in p]
    assert approval_paths, "expected the approval routes to exist"
    assert not any(p.startswith("/api/agent") for p in approval_paths)

    # No tool on the agent's surface can WRITE approval. Checked against the
    # store functions themselves rather than tool names: the surface legitimately
    # includes get_approved_applications, which only reads.
    import screening.store as store_module
    from agenttools.mcp_app import _TOOL_REGISTRY

    writers = {store_module.set_approval, store_module.mark_applied}
    assert not (writers & {fn for fn, _ in _TOOL_REGISTRY.values()})


def test_approving_without_a_letter_is_refused(client):
    """The agent applies with the stored letter verbatim, so approving with no
    letter would queue an application with nothing to send."""
    s = _deferred()
    r = client.patch(f"/api/screenings/{s.id}", json={"approval": "approved"})
    assert r.status_code == 409
    assert store.get(s.id).approval == "pending"


def test_approving_with_a_letter_succeeds(client):
    import coverletter.store as letters

    s = _deferred()
    letters.save(s.id, letters.CoverLetterDraft(text="Dear team,", source="operator"))
    r = client.patch(f"/api/screenings/{s.id}", json={"approval": "approved"})
    assert r.status_code == 200
    assert store.get(s.id).approval == "approved"


def test_rejecting_never_needs_a_letter(client):
    s = _deferred()
    assert client.patch(f"/api/screenings/{s.id}", json={"approval": "rejected"}).status_code == 200


def test_bulk_approve_reports_a_draftless_item_instead_of_approving_it(client):
    import coverletter.store as letters

    a, b = _deferred("Contoso Labs"), _deferred("Aperture")
    letters.save(a.id, letters.CoverLetterDraft(text="Dear team,"))
    body = client.patch(
        "/api/screenings/approvals", json={"ids": [a.id, b.id], "approval": "approved"}
    ).json()
    assert {r["id"]: r["ok"] for r in body["results"]} == {a.id: True, b.id: False}
    assert store.get(b.id).approval == "pending"


# ---------------------------------------------------------------------------
# POST /api/screenings/{id}/applied — the operator applied by hand
# ---------------------------------------------------------------------------

class TestMarkScreeningApplied:
    def _screening(self, client, **overrides):
        body = {
            "company": "Contoso Labs",
            "role": "Staff AI Engineer",
            "url": "https://contoso.example/jobs/1",
            "postingText": "Staff AI Engineer, Germany (Remote).",
            "verdict": "passed",
            **overrides,
        }
        r = client.post("/api/screenings", json=body)
        assert r.status_code == 201
        return r.json()["id"]

    def test_creates_an_application_from_the_screening(self, client, data_dir):
        sid = self._screening(client)
        r = client.post(f"/api/screenings/{sid}/applied")
        assert r.status_code == 201
        app = r.json()
        assert app["company"] == "Contoso Labs"
        assert app["role"] == "Staff AI Engineer"
        assert app["applicationUrl"] == "https://contoso.example/jobs/1"
        assert app["posting"] == "Staff AI Engineer, Germany (Remote)."
        assert app["submitted"] is True
        assert app["status"] == "Applied"
        assert app["captureMethod"] == "manual"
        assert app["applicationDate"]

    def test_the_application_is_listed_on_the_applications_page(self, client, data_dir):
        sid = self._screening(client)
        client.post(f"/api/screenings/{sid}/applied")
        apps = client.get("/api/applications").json()
        assert [a["company"] for a in apps] == ["Contoso Labs"]

    def test_the_screening_leaves_the_found_queue(self, client, data_dir):
        sid = self._screening(client)
        client.post(f"/api/screenings/{sid}/applied")
        record = next(s for s in client.get("/api/screenings").json() if s["id"] == sid)
        assert record["approval"] == "applied"
        assert sid not in [s["id"] for s in client.get("/api/screenings?approval=pending").json()]

    def test_applying_twice_does_not_create_a_duplicate(self, client, data_dir):
        """A double click must not put two rows on the Applications page."""
        sid = self._screening(client)
        assert client.post(f"/api/screenings/{sid}/applied").status_code == 201
        assert client.post(f"/api/screenings/{sid}/applied").status_code == 409
        assert len(client.get("/api/applications").json()) == 1

    def test_unknown_screening_is_404(self, client, data_dir):
        assert client.post("/api/screenings/nope/applied").status_code == 404

    def test_a_screening_with_a_url_is_a_posting_submission(self, client, data_dir):
        sid = self._screening(client, url="https://example.com/x")
        r = client.post(f"/api/screenings/{sid}/applied")
        assert r.json()["submissionType"] == "Posting"

    def test_a_screening_with_no_url_is_a_general_submission(self, client, data_dir):
        """The other branch of `"Posting" if screening.url else "General"`.

        The test that carried this name passed a URL and asserted "Posting",
        so the General branch had no coverage at all.
        """
        from screening import store as screening_store

        created = screening_store.create(
            {"company": "No URL Co", "role": "Engineer", "verdict": "passed"}
        )
        r = client.post(f"/api/screenings/{created.id}/applied")
        assert r.status_code == 201
        assert r.json()["submissionType"] == "General"

    def test_concurrent_applies_create_exactly_one_row(self, client, data_dir):
        """Two tabs, or a slow response and a second click, must not duplicate.

        The check-then-create-then-retire ordering let both requests pass the
        409 check and create two Applications rows for one posting.
        """
        import threading

        from screening import store as screening_store

        sid = self._screening(client)
        winners = []

        def claim():
            winners.append(screening_cl := screening_store.claim_for_apply(sid))

        threads = [threading.Thread(target=claim) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]

        assert sum(1 for w in winners if w is not None) == 1

    def test_a_failed_claim_creates_no_application(self, client, data_dir):
        """The row is created only by the caller that won the claim, so a
        losing request must leave the Applications page untouched."""
        sid = self._screening(client)
        assert client.post(f"/api/screenings/{sid}/applied").status_code == 201
        before = len(client.get("/api/applications").json())

        assert client.post(f"/api/screenings/{sid}/applied").status_code == 409

        assert len(client.get("/api/applications").json()) == before
