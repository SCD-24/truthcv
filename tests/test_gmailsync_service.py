"""gmailsync.service: per-application query scoping, closed-status filtering,
Jev-only classification/auto-apply with evidence notes, decline handling,
and dedupe.

Also covers screening.jev.confirm's fail-open behavior directly (HTTP
error/timeout/bad shape), alongside tests/test_screening_jev.py's patterns.
The Gmail HTTP layer and Jev are both mocked here — this suite must never
make a live call to either.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

import applications
import secretstore
from gmailsync import service
from gmailsync.store import load_suggestions
from screening import jev
from truth.answers import Answers, save as save_answers

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    """set_connection requires ENCRYPTION_KEY; several tests here write one."""
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)


def _make_app(**overrides):
    fields = {"company": "Acme Corp", "website": "https://acme.example", "status": "Applied"}
    fields.update(overrides)
    return applications.create(fields)


def _metadata(message_id: str, sender: str, subject: str, date: str, snippet: str) -> dict:
    return {
        "id": message_id,
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date},
            ]
        },
    }


class FakeGmailClient:
    """Stand-in for gmailsync.service.GmailClient: records queries, serves canned messages."""

    def __init__(self, messages_by_query=None, metadata_by_id=None, full_by_id=None):
        self.queries: list[str] = []
        self._messages_by_query = messages_by_query or {}
        self._metadata_by_id = metadata_by_id or {}
        self._full_by_id = full_by_id or {}
        self.metadata_calls = 0

    def list_messages(self, query: str) -> list[dict]:
        self.queries.append(query)
        return self._messages_by_query.get(query, [])

    def get_metadata(self, message_id: str) -> dict:
        self.metadata_calls += 1
        return self._metadata_by_id.get(message_id, {"snippet": "", "payload": {"headers": []}})

    def get_full(self, message_id: str) -> dict:
        return self._full_by_id.get(message_id, {"payload": {}})


class _AlwaysReturnsClient(FakeGmailClient):
    """A client that serves the same message id for any query text."""

    def list_messages(self, query: str) -> list[dict]:
        self.queries.append(query)
        return [{"id": "m1"}]


def _confirm_matching(keyword_by_statement: dict[str, str]):
    """jev.confirm fake: confirms a statement when its keyword is in the state text."""

    def fake(statement, state):
        keyword = keyword_by_statement.get(statement)
        return bool(keyword) and keyword in state

    return fake


# --- (1) per-application query construction --------------------------------


def test_application_query_scopes_by_domain_and_company(data_dir):
    app = _make_app(
        company="Acme Corp",
        website="https://www.acme.example/careers",
        application_url="https://jobs.acme.example/apply/123",
    )

    query = service._application_query(app, 0)
    assert "from:acme.example" in query
    assert "from:jobs.acme.example" in query
    assert "from:acme" in query
    assert '"Acme Corp"' in query
    assert "after:" not in query

    query_after = service._application_query(app, 1700000000)
    assert "after:1700000000" in query_after


def test_application_query_with_company_but_no_domains_still_searches(data_dir):
    app = _make_app(company="Acme Corp", website="", application_url="")

    query = service._application_query(app, 0)
    assert query != ""
    assert '"Acme Corp"' in query


def test_application_query_with_no_company_token_and_no_domains_is_skipped(data_dir):
    app = _make_app(company="!!!", website="", application_url="")

    query = service._application_query(app, 0)
    assert query == ""


def test_run_sync_issues_one_query_per_open_application_and_no_full_inbox_query(monkeypatch, data_dir):
    save_answers(Answers(email="me@example.com"))
    app1 = _make_app(company="Acme Corp", website="https://acme.example")
    app2 = _make_app(company="Globex Inc", website="https://globex.example", status="Waiting")
    client = FakeGmailClient()
    monkeypatch.setattr(service, "build_gmail_client", lambda: client)

    result = service.run_sync(force=True)

    assert result["skipped"] is False
    assert len(client.queries) == 2
    assert all("to:" not in q for q in client.queries)
    assert any("from:acme" in q for q in client.queries)
    assert any("from:globex" in q for q in client.queries)


# --- (2) Applied/Waiting candidate filter -----------------------------------


def test_pending_candidates_excludes_closed_statuses(data_dir):
    applied = _make_app(status="Applied")
    waiting = _make_app(status="Waiting")
    draft = _make_app(status="Draft", company="Initech", website="https://initech.example")
    blank = _make_app(status="")
    _make_app(status="Rejected")
    _make_app(status="Interviewing")
    _make_app(status="Offer")

    ids = {a.id for a in service._pending_candidates()}
    assert ids == {applied.id, waiting.id, draft.id, blank.id}


# --- (3) Rejected/Interviewing auto-apply with note evidence ---------------


def test_matched_rejection_and_interview_auto_apply_with_evidence(monkeypatch, data_dir):
    save_answers(Answers(email="me@example.com"))
    rejected_app = _make_app(company="Acme Corp", website="https://acme.example", status="Applied")
    interview_app = _make_app(company="Globex Inc", website="https://globex.example", status="Waiting")
    rejected_query = service._application_query(rejected_app, 0)
    interview_query = service._application_query(interview_app, 0)

    rejected_meta = _metadata(
        "m1", "Recruiter <no-reply@acme.example>", "Rejected update", "Mon, 1 Jan 2024 00:00:00 +0000", "We regret"
    )
    interview_meta = _metadata(
        "m2", "Talent <talent@globex.example>", "Interview invite", "Tue, 2 Jan 2024 00:00:00 +0000", "Let's chat"
    )
    client = FakeGmailClient(
        messages_by_query={rejected_query: [{"id": "m1"}], interview_query: [{"id": "m2"}]},
        metadata_by_id={"m1": rejected_meta, "m2": interview_meta},
    )
    monkeypatch.setattr(service, "build_gmail_client", lambda: client)
    monkeypatch.setattr(
        service.jev,
        "confirm",
        _confirm_matching(
            {
                service._CONFIRM_STATEMENTS["rejection"][0]: "Rejected update",
                service._CONFIRM_STATEMENTS["interview"][0]: "Interview invite",
            }
        ),
    )

    service.run_sync(force=True)

    updated_rejected = applications.get(rejected_app.id)
    assert updated_rejected.status == "Rejected"
    assert updated_rejected.response_received is True
    assert "m1" in updated_rejected.notes
    assert "no-reply@acme.example" in updated_rejected.notes
    assert "Rejected update" in updated_rejected.notes

    updated_interview = applications.get(interview_app.id)
    assert updated_interview.status == "Interviewing"
    assert updated_interview.response_received is True
    assert "m2" in updated_interview.notes

    suggestions = {s.id: s for s in load_suggestions()}
    assert suggestions["m1"].state == "applied"
    assert suggestions["m1"].decision == "confirmed"
    assert suggestions["m2"].state == "applied"
    assert suggestions["m2"].decision == "confirmed"
    assert service.pending_suggestions() == []


# --- (4) Jev decline leaves status untouched, suggestion pending -----------


def test_jev_decline_leaves_status_and_suggestion_pending(monkeypatch, data_dir):
    save_answers(Answers(email="me@example.com"))
    app = _make_app(company="Acme Corp", website="https://acme.example", status="Applied")
    query = service._application_query(app, 0)
    meta = _metadata("m1", "Recruiter <no-reply@acme.example>", "Update", "Mon, 1 Jan 2024 00:00:00 +0000", "regret")
    client = FakeGmailClient(messages_by_query={query: [{"id": "m1"}]}, metadata_by_id={"m1": meta})
    monkeypatch.setattr(service, "build_gmail_client", lambda: client)
    monkeypatch.setattr(service.jev, "confirm", lambda statement, state: False)

    service.run_sync(force=True)

    updated = applications.get(app.id)
    assert updated.status == "Applied"
    assert updated.response_received is False
    assert updated.notes == ""

    suggestions = load_suggestions()
    assert len(suggestions) == 1
    assert suggestions[0].state == "pending"
    assert suggestions[0].classification == "other"
    assert suggestions[0].decision == ""
    assert len(service.pending_suggestions()) == 1


# --- (5) processed-id dedupe ------------------------------------------------


def test_low_confidence_match_does_not_auto_apply(monkeypatch, data_dir):
    save_answers(Answers(email="me@example.com"))
    app = _make_app(company="Acme Corp", website="https://acme.example", status="Applied")
    query = service._application_query(app, 0)
    meta = _metadata(
        "m1",
        "Recruiter <news@unrelated-domain.example>",
        "Acme Corp rejected your application",
        "Mon, 1 Jan 2024 00:00:00 +0000",
        "regret to inform",
    )
    client = FakeGmailClient(messages_by_query={query: [{"id": "m1"}]}, metadata_by_id={"m1": meta})
    monkeypatch.setattr(service, "build_gmail_client", lambda: client)
    monkeypatch.setattr(
        service.jev,
        "confirm",
        _confirm_matching({service._CONFIRM_STATEMENTS["rejection"][0]: "Acme Corp rejected your application"}),
    )

    service.run_sync(force=True)

    updated = applications.get(app.id)
    assert updated.status == "Applied"
    assert updated.response_received is False
    assert updated.notes == ""

    suggestions = {s.id: s for s in load_suggestions()}
    assert suggestions["m1"].match_confidence == "low"
    assert suggestions["m1"].state == "pending"
    assert suggestions["m1"].decision == ""
    assert suggestions["m1"].classification == "rejection"
    assert suggestions["m1"].suggested_status == "Rejected"


def test_draft_with_non_draft_sibling_company_is_not_a_candidate(monkeypatch, data_dir):
    save_answers(Answers(email="me@example.com"))
    applied_app = _make_app(company="Acme Corp", website="https://acme.example", status="Applied")
    draft_app = _make_app(company="Acme Corp", website="https://acme.example", status="Draft")
    query = service._application_query(applied_app, 0)
    meta = _metadata(
        "m1", "Recruiter <no-reply@acme.example>", "Rejected update", "Mon, 1 Jan 2024 00:00:00 +0000", "We regret"
    )
    client = FakeGmailClient(messages_by_query={query: [{"id": "m1"}]}, metadata_by_id={"m1": meta})
    monkeypatch.setattr(service, "build_gmail_client", lambda: client)
    monkeypatch.setattr(
        service.jev,
        "confirm",
        _confirm_matching({service._CONFIRM_STATEMENTS["rejection"][0]: "Rejected update"}),
    )

    service.run_sync(force=True)

    updated_applied = applications.get(applied_app.id)
    assert updated_applied.status == "Rejected"
    assert updated_applied.response_received is True

    updated_draft = applications.get(draft_app.id)
    assert updated_draft.status == "Draft"
    assert updated_draft.response_received is False
    assert updated_draft.notes == ""

    suggestions = {s.id: s for s in load_suggestions()}
    assert suggestions["m1"].application_id == applied_app.id
    assert suggestions["m1"].state == "applied"


def test_dedupes_message_id_appearing_in_multiple_app_queries(monkeypatch, data_dir):
    save_answers(Answers(email="me@example.com"))
    _make_app(company="Acme Corp", website="https://acme.example", status="Applied")
    _make_app(company="Acme Staffing", website="https://acme-staffing.example", status="Waiting")
    meta = _metadata("m1", "Recruiter <no-reply@acme.example>", "Update", "Mon, 1 Jan 2024 00:00:00 +0000", "regret")
    client = _AlwaysReturnsClient(metadata_by_id={"m1": meta})
    monkeypatch.setattr(service, "build_gmail_client", lambda: client)

    result = service.run_sync(force=True)

    assert result["processed"] == 1
    assert client.metadata_calls == 1


def test_processed_message_ids_dedupe_across_runs(monkeypatch, data_dir):
    save_answers(Answers(email="me@example.com"))
    _make_app(company="Acme Corp", website="https://acme.example", status="Applied")
    meta = _metadata("m1", "Recruiter <no-reply@acme.example>", "Update", "Mon, 1 Jan 2024 00:00:00 +0000", "regret")
    client = _AlwaysReturnsClient(metadata_by_id={"m1": meta})
    monkeypatch.setattr(service, "build_gmail_client", lambda: client)

    first = service.run_sync(force=True)
    assert first["processed"] == 1
    assert client.metadata_calls == 1

    second = service.run_sync(force=True)
    assert second["processed"] == 0
    assert client.metadata_calls == 1


# --- confirm() fail-open coverage (beside tests/test_screening_jev.py) -----


class _FakeResponse:
    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_urlopen(monkeypatch, handler):
    def fake_urlopen(request, timeout=None):
        result = handler(request)
        if isinstance(result, Exception):
            raise result
        return _FakeResponse(result)

    monkeypatch.setattr(jev.urllib.request, "urlopen", fake_urlopen)


def test_confirm_false_when_email_tracking_disabled_by_default(data_dir, monkeypatch):
    secretstore.set_connection("jev", {"apiKey": "jev_secret"})

    def handler(request):
        raise AssertionError("should not be called")

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.confirm("This is a rejection.", "body text") is False


def test_confirm_true_when_score_at_or_above_threshold(data_dir, monkeypatch):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForEmailTracking": True})

    def handler(request):
        return {"answers": {"decision": {"noul": 0.9}}}

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.confirm("This is a rejection.", "body text") is True


def test_confirm_false_when_score_below_threshold(data_dir, monkeypatch):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForEmailTracking": True})

    def handler(request):
        return {"answers": {"decision": {"noul": 0.5}}}

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.confirm("This is a rejection.", "body text") is False


def test_confirm_fail_open_on_http_error(data_dir, monkeypatch, caplog):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForEmailTracking": True})

    def handler(request):
        return urllib.error.HTTPError(jev.API_URL, 500, "Server Error", {}, None)

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.confirm("This is a rejection.", "body text") is False
    assert "jev_secret" not in caplog.text


def test_confirm_fail_open_on_timeout(data_dir, monkeypatch):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForEmailTracking": True})

    def handler(request):
        return TimeoutError("timed out")

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.confirm("This is a rejection.", "body text") is False


def test_confirm_fail_open_on_bad_response_shape(data_dir, monkeypatch):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForEmailTracking": True})

    def handler(request):
        return []

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.confirm("This is a rejection.", "body text") is False
