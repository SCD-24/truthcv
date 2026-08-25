"""The agent's read-only view of the approved queue, and its failure reporting.

Two hazards are guarded server-side rather than by prompt: an item already
applied to must not be handed back (the retry policy would double-submit), and
a company in cooldown must come back flagged rather than vanish, so the agent
reports why it did not go out.
"""

from __future__ import annotations

import pytest

import applications.store as apps
import screening.store as store
from agenttools import tools_ledger
from agenttools.tools_ledger import get_approved_applications, report_apply_failure
from companyresearch import store as findings_store


def _approved(company="Contoso Labs", url="https://contoso.example/jobs/1"):
    s = store.create(
        {"company": company, "role": "Staff", "url": url, "verdict": "deferred"}
    )
    store.set_approval(s.id, "approved")
    return s


def test_returns_approved_items(data_dir):
    s = _approved()
    items = get_approved_applications()
    assert [(i["screening_id"], i["company"], i["url"]) for i in items] == [
        (s.id, "Contoso Labs", "https://contoso.example/jobs/1")
    ]


def test_excludes_pending_and_rejected(data_dir):
    store.create({"company": "A", "verdict": "deferred"})
    r = store.create({"company": "B", "verdict": "deferred"})
    store.set_approval(r.id, "rejected")
    assert get_approved_applications() == []


def test_already_applied_url_is_flagged_not_hidden(data_dir):
    """Retry-forever would otherwise re-submit an application whose confirmation
    capture failed. It comes back flagged, so a queued item that stops moving
    says why instead of vanishing from every run at zero attempts."""
    _approved(url="https://contoso.example/jobs/1")
    apps.create(
        {
            "company": "Contoso Labs",
            "application_url": "https://contoso.example/jobs/1",
            "submitted": True,
        }
    )
    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["already_applied"]


def test_open_contradiction_blocks_but_does_not_hide_the_item(data_dir):
    """A company whose own research disagrees with itself must not be applied
    to, but the agent still needs to see the item to report why it did not go
    out — the same discipline cooldown uses."""
    _approved(company="Contoso Labs")
    findings_store.record(
        "Contoso Labs", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent"
    )
    findings_store.record(
        "Contoso Labs", "employer_rating", "3.0", "https://b.example/y", "review_site", "", "agent"
    )

    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["contradictory_research"]
    assert items[0]["contradictions"]
    assert items[0]["contradictions"][0]["claim"] == "employer_rating"


def test_resolving_the_contradiction_clears_the_block(data_dir):
    first = findings_store.record(
        "Contoso Labs", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent"
    )
    findings_store.record(
        "Contoso Labs", "employer_rating", "3.0", "https://b.example/y", "review_site", "", "agent"
    )
    _approved(company="Contoso Labs")
    findings_store.resolve(first.id, "rejected")

    items = get_approved_applications()
    assert items[0]["blocked_reason"] != "contradictory_research"
    assert items[0]["contradictions"] == []


def test_already_applied_outranks_contradictory_research(data_dir):
    _approved(company="Contoso Labs", url="https://contoso.example/jobs/1")
    apps.create(
        {
            "company": "Contoso Labs",
            "application_url": "https://contoso.example/jobs/1",
            "submitted": True,
        }
    )
    findings_store.record(
        "Contoso Labs", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent"
    )
    findings_store.record(
        "Contoso Labs", "employer_rating", "3.0", "https://b.example/y", "review_site", "", "agent"
    )

    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["already_applied"]


def test_unsubmitted_ledger_row_does_not_block(data_dir):
    """The ledger also holds reconstructed placeholders for postings nobody
    applied to. Matching one hid a legitimately approved item from every run."""
    import coverletter.store as letters

    s = _approved(url="https://contoso.example/jobs/1")
    letters.save(s.id, letters.CoverLetterDraft(text="Dear team,"))
    apps.create(
        {
            "company": "Contoso Labs",
            "application_url": "https://contoso.example/jobs/1",
            "submitted": False,
            "status": "pending",
        }
    )
    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == [""]


def test_confirmation_text_counts_as_a_submission(data_dir):
    """Rows predating `record_application` naming `submitted` can carry False
    despite having gone out; a captured confirmation is the corroboration."""
    import applications.store as apps_store
    from applications.model import Confirmation

    _approved(url="https://contoso.example/jobs/1")
    a = apps.create(
        {
            "company": "Contoso Labs",
            "application_url": "https://contoso.example/jobs/1",
            "submitted": False,
        }
    )
    apps_store.save_confirmation(a.id, Confirmation(text="Application submitted!"))
    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["already_applied"]


def test_already_applied_outranks_cooldown(data_dir):
    """Both hazards can name the same item; already_applied is the one that
    says it must not go out at all rather than not yet."""
    import agentconfig.store as agent_config_store

    s = _approved(url="https://contoso.example/jobs/1")
    apps.create(
        {
            "company": "Contoso Labs",
            "application_url": "https://contoso.example/jobs/1",
            "submitted": True,
        }
    )
    cfg = agent_config_store.load()
    cfg.blocked_companies = [s.company]
    agent_config_store.save(cfg)

    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["already_applied"]


def test_record_application_marks_the_row_submitted(data_dir):
    """The guard above keys on `submitted`; a row the agent records with it
    still False would hand the same posting back on the next run."""
    from agenttools.tools_ledger import record_application

    created = record_application(
        company="Contoso Labs", application_url="https://contoso.example/jobs/1"
    )
    assert created["submitted"] is True


def test_record_application_can_record_an_unsubmitted_row(data_dir):
    from agenttools.tools_ledger import record_application

    created = record_application(company="Contoso Labs", submitted=False)
    assert created["submitted"] is False


def test_report_apply_failure_counts_and_keeps_approval(data_dir):
    s = _approved()
    report_apply_failure(s.id, "browser died")
    reloaded = store.get(s.id)
    assert reloaded.apply_attempts == 1
    assert reloaded.apply_error == "browser died"
    assert reloaded.approval == "approved"


def test_report_apply_failure_unknown_id(data_dir):
    assert report_apply_failure("nope", "x")["ok"] is False


def test_no_url_flagged_blocked_reason(data_dir):
    """Imported records with no URL give the agent nothing to open; they must
    come back flagged instead of silently handed to the agent to flail on."""
    _approved(url="")
    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["no_url"]


def test_url_present_no_cooldown_blocked_reason_empty(data_dir):
    import coverletter.store as letters

    s = _approved(url="https://contoso.example/jobs/1")
    letters.save(s.id, letters.CoverLetterDraft(text="Dear team,"))
    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == [""]


def test_approved_item_carries_the_stored_letter(data_dir):
    """The agent applies with the operator's text verbatim; regenerating would
    discard the edit, which is the whole point of semi-auto."""
    import coverletter.store as letters

    s = _approved()
    letters.save(s.id, letters.CoverLetterDraft(text="My own words.", source="operator"))
    item = get_approved_applications()[0]
    assert item["cover_letter"] == "My own words."
    assert item["letter_source"] == "operator"


def test_approved_item_without_a_letter_reports_empty(data_dir):
    s = _approved()
    item = get_approved_applications()[0]
    assert item["cover_letter"] == ""
    assert item["letter_source"] == ""


def test_approved_item_with_letter_deleted_after_approval_is_blocked(data_dir):
    """The approval gate only checks at approval time; a draft deleted after
    approval must still stop the agent from applying with nothing to send."""
    import coverletter.store as letters

    s = _approved()
    letters.save(s.id, letters.CoverLetterDraft(text="Dear team,"))
    letters.delete(s.id)
    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["no_letter"]


def test_approved_item_with_blank_letter_is_blocked(data_dir):
    """A store-level blank draft (the route rejects this, but the guard here
    must hold regardless of how the draft went blank) reports no_letter too."""
    import coverletter.store as letters

    s = _approved()
    letters.save(s.id, letters.CoverLetterDraft(text="   "))
    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["no_letter"]


def test_approved_item_with_a_real_letter_is_unblocked(data_dir):
    import coverletter.store as letters

    s = _approved()
    letters.save(s.id, letters.CoverLetterDraft(text="Dear team,"))
    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == [""]


def test_cooldown_takes_precedence_over_a_missing_letter(data_dir):
    """Both hazards apply to the same item; the report must name one reason,
    and cooldown is the more urgent of the two."""
    import agentconfig.store as agent_config_store
    import coverletter.store as letters

    s = _approved()
    letters.delete(s.id)
    cfg = agent_config_store.load()
    cfg.blocked_companies = [s.company]
    agent_config_store.save(cfg)

    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["cooldown"]


def test_record_application_is_idempotent_per_screening_id_reproducing_initech(data_dir):
    """The Initech incident: four record_application calls against one approved
    queue item must write ONE application row, not four. The idempotency keys on
    screening_id; a re-record improves the same row, a malformed evidence
    payload persists nothing, and the item ends up retired and double-submit
    guarded."""
    s = _approved(company="Initech", url="https://initech.example/jobs/4d090169/")

    # 1st: minimal args create the row.
    created = tools_ledger.record_application(
        screening_id=s.id,
        application_url="https://initech.example/jobs/4d090169/application",
    )
    assert created["created"] is True
    first_id = created["id"]

    # 2nd: fields_submitted arrives as a JSON-encoded STRING (the actual bug).
    created = tools_ledger.record_application(
        screening_id=s.id,
        fields_submitted='[{"label": "resume", "value": "attached", "source": "operator"}]',
    )
    assert created["created"] is False
    assert created["id"] == first_id

    # 3rd: confirmation arrives as a JSON-encoded string.
    created = tools_ledger.record_application(
        screening_id=s.id,
        confirmation='{"text": "Application submitted!", "confirmed_at": "2026-02-01"}',
    )
    assert created["created"] is False
    assert created["id"] == first_id

    # 4th: genuinely malformed evidence must raise and persist nothing.
    with pytest.raises(ValueError):
        tools_ledger.record_application(
            screening_id=s.id,
            attachments="not valid json{{{",
        )

    # Exactly one row exists, carrying the evidence calls 2 and 3 persisted.
    initech_rows = [a for a in apps.load_all() if a.company == "Initech"]
    assert len(initech_rows) == 1
    row = initech_rows[0]
    assert row.id == first_id
    assert [(f.label, f.value) for f in row.fields_submitted] == [("resume", "attached")]
    assert row.confirmation.text == "Application submitted!"

    # The approved item is retired once its application is confirmed.
    assert store.get(s.id).approval == "applied"

    # Re-approving surfaces it in the queue again, and the double-submit guard
    # now flags it: the submission row keys on the same screening_id.
    store.set_approval(s.id, "approved")
    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["already_applied"]


def test_record_application_malformed_evidence_persists_nothing(data_dir):
    """Parse-before-write: a malformed evidence payload raises before any store
    write, so no orphan application row is left behind."""
    s = _approved(company="Initech", url="https://initech.example/jobs/orphan/")

    with pytest.raises(ValueError):
        tools_ledger.record_application(screening_id=s.id, confirmation="{not json")

    assert apps.load_all() == []
