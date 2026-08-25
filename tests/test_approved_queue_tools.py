"""The agent's read-only view of the approved queue, and its failure reporting.

Two hazards are guarded server-side rather than by prompt: an item already
applied to must not be handed back (the retry policy would double-submit), and
a company in cooldown must come back flagged rather than vanish, so the agent
reports why it did not go out.
"""

from __future__ import annotations

import applications.store as apps
import screening.store as store
from agenttools.tools_ledger import get_approved_applications, report_apply_failure


def _approved(company="Grafana Labs", url="https://grafana.com/jobs/1"):
    s = store.create(
        {"company": company, "role": "Staff", "url": url, "verdict": "deferred"}
    )
    store.set_approval(s.id, "approved")
    return s


def test_returns_approved_items(data_dir):
    s = _approved()
    items = get_approved_applications()
    assert [(i["screening_id"], i["company"], i["url"]) for i in items] == [
        (s.id, "Grafana Labs", "https://grafana.com/jobs/1")
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
    _approved(url="https://grafana.com/jobs/1")
    apps.create(
        {
            "company": "Grafana Labs",
            "application_url": "https://grafana.com/jobs/1",
            "submitted": True,
        }
    )
    items = get_approved_applications()
    assert [i["blocked_reason"] for i in items] == ["already_applied"]


def test_unsubmitted_ledger_row_does_not_block(data_dir):
    """The ledger also holds reconstructed placeholders for postings nobody
    applied to. Matching one hid a legitimately approved item from every run."""
    import coverletter.store as letters

    s = _approved(url="https://grafana.com/jobs/1")
    letters.save(s.id, letters.CoverLetterDraft(text="Dear team,"))
    apps.create(
        {
            "company": "Grafana Labs",
            "application_url": "https://grafana.com/jobs/1",
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

    _approved(url="https://grafana.com/jobs/1")
    a = apps.create(
        {
            "company": "Grafana Labs",
            "application_url": "https://grafana.com/jobs/1",
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

    s = _approved(url="https://grafana.com/jobs/1")
    apps.create(
        {
            "company": "Grafana Labs",
            "application_url": "https://grafana.com/jobs/1",
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
        company="Grafana Labs", application_url="https://grafana.com/jobs/1"
    )
    assert created["submitted"] is True


def test_record_application_can_record_an_unsubmitted_row(data_dir):
    from agenttools.tools_ledger import record_application

    created = record_application(company="Grafana Labs", submitted=False)
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

    s = _approved(url="https://grafana.com/jobs/1")
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
