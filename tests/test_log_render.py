"""APPLICATION_LOG.md renderer: rendering, and the completeness guard.

The guard is the reason this module was ported out of the retired Jobs repo,
so most of these tests are about `write_log` REFUSING rather than about the
Markdown it produces: a log that silently omits an application is worse than
no log at all, because it reads as a complete account.
"""

import pytest

from applications.log_render import (
    RenderRefused,
    render_log,
    write_log,
)
from applications.model import (
    Application,
    Attachment,
    Confirmation,
    FieldSubmitted,
    Glassdoor,
    Screening,
)


def _app(app_id, company="Acme GmbH", **kwargs):
    """A minimally-populated Application, overridable per test."""
    fields = {
        "id": app_id,
        "company": company,
        "role": "Integration Engineer",
        "application_url": "https://example.test/jobs/1",
        "application_date": "2026-01-02",
        "status": "confirmed",
        "submitted": True,
    }
    fields.update(kwargs)
    app = Application(**fields)
    app.confirmation = Confirmation(text="Your application has been received")
    return app


def test_every_application_is_accounted_for_exactly_once(tmp_path):
    """The whole ledger renders, each record carrying its marker once."""
    apps = [_app("aaa111aaa111"), _app("bbb222bbb222", company="Beta AG")]
    target = write_log(apps, tmp_path / "log" / "APPLICATION_LOG.md")

    text = target.read_text()
    assert text.count("<!-- record: aaa111aaa111 -->") == 1
    assert text.count("<!-- record: bbb222bbb222 -->") == 1
    assert "Acme GmbH" in text and "Beta AG" in text


def test_duplicate_ids_are_refused_and_leave_the_previous_log_untouched(tmp_path):
    """Two records sharing an id must not silently collapse into one section."""
    target = tmp_path / "APPLICATION_LOG.md"
    target.write_text("PREVIOUS LOG\n")

    with pytest.raises(RenderRefused) as refusal:
        write_log([_app("dup000dup000"), _app("dup000dup000", company="Other")], target)

    assert "dup000dup000" in str(refusal.value)
    assert target.read_text() == "PREVIOUS LOG\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_an_unrendered_application_is_refused(tmp_path, monkeypatch):
    """If the rendered text drops a record, the write is refused.

    Simulates a renderer regression by rendering only the first application,
    which is exactly the failure the marker count exists to catch.
    """
    import applications.log_render as module

    monkeypatch.setattr(module, "render_log", lambda apps: module.HEADER)
    target = tmp_path / "APPLICATION_LOG.md"

    with pytest.raises(RenderRefused) as refusal:
        module.write_log([_app("ccc333ccc333")], target)

    assert "ccc333ccc333" in str(refusal.value)
    assert not target.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_write_leaves_no_temp_file_behind(tmp_path):
    """The atomic write cleans up after itself on the success path too."""
    write_log([_app("ddd444ddd444")], tmp_path / "APPLICATION_LOG.md")
    assert not list(tmp_path.glob("*.tmp"))


def test_migrated_multi_notes_render_as_separate_bullets():
    """`notes` is one string; blank lines restore the separate Jobs notes."""
    app = _app("eee555eee555", notes="First observation\n\nSecond observation")
    text = render_log([app])
    assert "- First observation" in text
    assert "- Second observation" in text


def test_both_status_vocabularies_render_without_translation():
    """Migrated `confirmed` and the tracker's own statuses both survive."""
    confirmed = render_log([_app("fff666fff666")])
    assert 'SUBMITTED — confirmed ("Your application has been received")' in confirmed

    rejected = _app("999aaa999aaa", status="Rejected")
    rejected.confirmation = Confirmation(text="")
    assert "REJECTED — submitted" in render_log([rejected])


def test_confirmation_survives_on_a_record_whose_status_moved_on():
    """A rejected-but-confirmed record keeps its submission evidence."""
    app = _app("777bbb777bbb", status="Rejected")
    text = render_log([app])
    assert '- **Confirmation:** "Your application has been received"' in text


def test_submitted_fields_render_with_their_provenance_and_escape_pipes():
    """The evidence trail reaches the log, table-safe."""
    app = _app("888ccc888ccc")
    app.fields_submitted = [
        FieldSubmitted(label="Salary", value="EUR 95,000 | negotiable", source="canonical")
    ]
    text = render_log([app])
    assert "| Salary | EUR 95,000 \\| negotiable | canonical |" in text


def test_screening_and_attachments_and_gaps_reach_the_log():
    """Everything the Jobs log carried per record still appears."""
    app = _app("999ddd999ddd", capture_method="reconstructed")
    app.screening = Screening(
        entity="German GmbH",
        remote="Fully remote",
        glassdoor=Glassdoor(rating="4.1", reviews="120"),
    )
    app.attachments = [Attachment(kind="cv", path="cv_999ddd999ddd.pdf")]
    app.gaps_disclosed = ["No Kubernetes production experience"]

    text = render_log([app])
    assert "- **Entity:** German GmbH" in text
    assert "- **Glassdoor:** 4.1 (120 reviews)" in text
    assert "- **Attachments:** cv_999ddd999ddd.pdf" in text
    assert "- No Kubernetes production experience" in text
    assert "reconstructed from the hand-written log" in text


def test_records_without_a_date_or_role_still_render():
    """22 pre-existing ledger rows carry no role; none may be dropped."""
    app = Application(id="000eee000eee", company="Sparse Ltd")
    text = render_log([app])
    assert "<!-- record: 000eee000eee -->" in text
    assert "role not recorded" in text
    assert "- **Date:** not recorded" in text


def test_profile_name_appears_when_set():
    """Profile field is rendered when present."""
    app = _app("111fff111fff", profile="Senior Python")
    text = render_log([app])
    assert "- **Profile:** Senior Python" in text


def test_profile_omitted_when_blank():
    """Blank profile renders identically to pre-profile records."""
    app_with_blank = _app("222ggg222ggg", profile="")
    app_without = _app("333hhh333hhh")
    
    text_blank = render_log([app_with_blank])
    text_without = render_log([app_without])
    
    # Both should omit the profile line
    assert "- **Profile:**" not in text_blank
    assert "- **Profile:**" not in text_without
