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


def test_excludes_already_applied_url(data_dir):
    """Retry-forever would otherwise re-submit an application whose confirmation
    capture failed."""
    _approved(url="https://grafana.com/jobs/1")
    apps.create(
        {"company": "Grafana Labs", "application_url": "https://grafana.com/jobs/1"}
    )
    assert get_approved_applications() == []


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
    _approved(url="https://grafana.com/jobs/1")
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
