"""Application model: legacy defaults and full nested-evidence shapes.

The nested-evidence fixture is shaped like a real Jobs applications/records/*.json
entry — specifically
2026-08-13_recare-deutschland-gmbh_ai-ml-engineer-m-w-d.json — so the evidence
dataclasses (Confirmation, Screening/Glassdoor, FieldSubmitted, Attachment) are
exercised against an actual production record shape and actual production
values (confirmation.confirmed_at/evidence, numeric Glassdoor rating/reviews),
not invented ones.
"""

from __future__ import annotations

import applications
from applications.model import (
    Application,
    Attachment,
    Confirmation,
    Document,
    FieldSubmitted,
    Glassdoor,
    Screening,
)
from applications.store import (
    save_attachments,
    save_confirmation,
    save_fields_submitted,
    save_screening,
)


# --- Legacy defaults -------------------------------------------------------

def test_document_from_dict_none_and_empty():
    assert Document.from_dict(None) is None
    assert Document.from_dict({}) is None


def test_field_submitted_defaults():
    assert FieldSubmitted.from_dict(None) == FieldSubmitted(label="", value="", source="")
    assert FieldSubmitted.from_dict({}) == FieldSubmitted(label="", value="", source="")


def test_confirmation_defaults():
    assert Confirmation.from_dict(None) == Confirmation(text="", confirmed_at="", evidence="")
    assert Confirmation.from_dict({}) == Confirmation(text="", confirmed_at="", evidence="")


def test_glassdoor_defaults():
    assert Glassdoor.from_dict(None) == Glassdoor(
        rating="", reviews="", waiver_applied=False, note=""
    )


def test_screening_defaults_include_nested_glassdoor_default():
    screening = Screening.from_dict(None)
    assert screening.entity == ""
    assert screening.remote == ""
    assert screening.salary == ""
    assert screening.language == ""
    assert screening.role_type == ""
    assert screening.glassdoor == Glassdoor()


def test_attachment_defaults():
    assert Attachment.from_dict(None) == Attachment(kind="", path="")


def test_application_from_dict_legacy_record_defaults_nested_evidence():
    """An old-shape record with none of the evidence keys at all must still
    load, with every nested evidence field at its dataclass default."""
    legacy = {
        "id": "abc123",
        "company": "EPAM",
        "submitted": True,
        "submission_type": "General",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    app = Application.from_dict(legacy)
    assert app.company == "EPAM"
    assert app.submitted is True
    assert app.fields_submitted == []
    assert app.confirmation == Confirmation()
    assert app.screening == Screening()
    assert app.attachments == []
    assert app.cv_document is None
    assert app.cover_letter_document is None


# --- Full nested evidence shape, real Jobs-shaped fixture ------------------

# Values below are lifted verbatim from the Jobs repo's
# applications/records/2026-08-13_recare-deutschland-gmbh_ai-ml-engineer-m-w-d.json,
# with the candidate's name and CV filename replaced by synthetic placeholders
# (confirmation.confirmed_at/evidence and screening.glassdoor's numeric rating,
# reviews and waiver_applied in particular are untouched) so the round trip is
# checked against real evidence, not an invented shape.
RECARE_FIXTURE = {
    "id": "a1b2c3d4e5f6",
    "company": "Recare Deutschland GmbH",
    "website": "https://recaresolutions.com",
    "application_url": "https://careers.recaresolutions.com/o/ai-ml-engineer-mwd",
    "submitted": True,
    "submission_type": "Tailored",
    "reached_out": False,
    "to_who": "",
    "response_received": False,
    "method": "",
    "posting": "AI / ML Engineer (m/w/d)",
    "application_date": "2026-08-13",
    "status": "confirmed",
    "notes": "Submitted in error window disclosed in gaps_disclosed.",
    "role": "AI / ML Engineer (m/w/d)",
    "ats": "other",
    "capture_method": "observed",
    "gaps_disclosed": [
        "Deep learning / model training. \"I have never trained or fine-tuned "
        "a model.\"",
    ],
    "fields_submitted": [
        {
            "label": "Full name *",
            "value": "Ada Example",
            "source": "canonical",
        },
        {
            "label": "CV or resume * (file)",
            "value": (
                "2026_Ada_Example_CV_v2.pdf \u2014 input candidate.cv reads "
                "C:\\fakepath\\2026_Ada_Example_CV_v2.pdf, upload verified=true, "
                "107624 bytes"
            ),
            "source": "observed",
        },
    ],
    "confirmation": {
        "text": "All done! Your application has been successfully submitted!",
        "confirmed_at": "2026-08-13T09:27:00+02:00",
        "evidence": (
            "Page navigated to "
            "https://careers.recaresolutions.com/o/ai-ml-engineer-mwd/applied "
            "and the Application tab relabelled itself \"Application \u2014 Applied\"."
        ),
    },
    "screening": {
        "entity": (
            "Recare Deutschland GmbH, Bertha-Benz-Stra\u00dfe 5, 10557 Berlin \u2014 "
            "HRB 169691 B, Amtsgericht Charlottenburg (Berlin), managing director "
            "Maximilian Greschke, read off Recare's own Impressum."
        ),
        "remote": (
            "Passes, with a mild internal conflict raised in the letter. The "
            "employer's own posting header reads \"Remote \u2014 Berlin, Berlin, "
            "Germany\"."
        ),
        "salary": (
            "not stated by the employer \u2014 the Recruitee offer carries an "
            "empty salary object (min/max/period/currency all null)."
        ),
        "language": (
            "English posting on the employer's own board, with no "
            "German-language requirement anywhere in the description or the "
            "requirements."
        ),
        "role_type": (
            "Target category \u2014 agentic / AI engineering, not a "
            "data-engineering fallback and not generic full-stack."
        ),
        "glassdoor": {
            "rating": 3.3,
            "reviews": 17,
            "waiver_applied": True,
            "note": (
                "Read directly in the browser off Glassdoor's own company page, "
                "not from a search snippet (the Jimdo rule). Profile "
                "**E2145485**, identified as the right company by four "
                "independent markers on that page: HQ **Berlin, Deutschland**, "
                "founded **2017**, CEO **Maximilian Greschke** (the same person "
                "named as managing director in the Impressum), and website "
                "**recaresolutions.com**. Rating **3,3 \u2605**. The page reports "
                "its review count inconsistently \u2014 the overview header says "
                "\"Basierend auf 8 Bewertungen\" while the FAQ says \"basierend "
                "auf **17** anonymen Bewertungen\"; the higher of the two is "
                "recorded here, since the waiver has to survive the least "
                "favourable reading. **17 < 20, so the \u00a72.5 under-20-reviews "
                "waiver applies** and the 3.3 rating does not reject. Note that "
                "the rating is below the 3.5 bar and would fail without the "
                "waiver, and that other sentiment figures on the page are weak "
                "(54% would recommend, 37% positive business outlook, 61% "
                "approve of CEO). A second, smaller Glassdoor profile literally "
                "named \"Recare\" exists (E4906785, 3.1\u2605, 5 reviews) and is "
                "also under 20 reviews, so the waiver holds on either profile."
            ),
        },
    },
    "attachments": [
        {"kind": "cv", "path": "2026_Ada_Example_CV_v2.pdf"},
        {"kind": "cover_letter", "path": "scratchpad/recare_cover.pdf"},
    ],
    "cv_document": None,
    "cover_letter_document": None,
    "created_at": "2026-08-13T07:27:00+00:00",
    "updated_at": "2026-08-13T07:27:00+00:00",
}


def test_full_nested_evidence_shape_exact_round_trip():
    app = Application.from_dict(RECARE_FIXTURE)

    # Confirmation evidence matches the real record exactly (hard-coded here,
    # not read back off the fixture, so a typo in either place cannot hide).
    assert app.confirmation.text == (
        "All done! Your application has been successfully submitted!"
    )
    assert app.confirmation.confirmed_at == "2026-08-13T09:27:00+02:00"
    assert app.confirmation.evidence == (
        "Page navigated to "
        "https://careers.recaresolutions.com/o/ai-ml-engineer-mwd/applied "
        "and the Application tab relabelled itself \"Application \u2014 Applied\"."
    )

    # Glassdoor numeric data matches the real record exactly.
    assert app.screening.glassdoor.rating == 3.3
    assert app.screening.glassdoor.reviews == 17
    assert app.screening.glassdoor.waiver_applied is True

    # Whole-record round trip is exact.
    assert app.to_dict() == RECARE_FIXTURE


# --- Generic editable writes refuse structured fields; setters persist them -

def test_create_and_update_ignore_structured_fields(data_dir):
    app = applications.create(
        {
            "company": "Recare Deutschland GmbH",
            "status": "confirmed",
            # Structured/nested fields are not in Application.EDITABLE and
            # must be silently ignored by the generic create path.
            "confirmation": RECARE_FIXTURE["confirmation"],
            "screening": RECARE_FIXTURE["screening"],
            "fields_submitted": RECARE_FIXTURE["fields_submitted"],
            "attachments": RECARE_FIXTURE["attachments"],
        }
    )
    assert app.company == "Recare Deutschland GmbH"
    assert app.status == "confirmed"
    assert app.confirmation == Confirmation()
    assert app.screening == Screening()
    assert app.fields_submitted == []
    assert app.attachments == []

    updated = applications.update(
        app.id,
        {
            "notes": "Updated notes",
            "confirmation": RECARE_FIXTURE["confirmation"],
            "screening": RECARE_FIXTURE["screening"],
        },
    )
    assert updated.notes == "Updated notes"
    assert updated.confirmation == Confirmation()
    assert updated.screening == Screening()

    # Persisted, not just in-memory: reload shows the same refusal.
    reloaded = applications.get(app.id)
    assert reloaded.confirmation == Confirmation()
    assert reloaded.screening == Screening()


def test_dedicated_setters_persist_structured_fields(data_dir):
    app = applications.create({"company": "Recare Deutschland GmbH"})

    saved = save_confirmation(app.id, RECARE_FIXTURE["confirmation"])
    assert saved.confirmation.confirmed_at == "2026-08-13T09:27:00+02:00"
    assert saved.confirmation.evidence == RECARE_FIXTURE["confirmation"]["evidence"]

    saved = save_screening(app.id, RECARE_FIXTURE["screening"])
    assert saved.screening.glassdoor.rating == 3.3
    assert saved.screening.glassdoor.reviews == 17
    assert saved.screening.glassdoor.waiver_applied is True

    saved = save_fields_submitted(app.id, RECARE_FIXTURE["fields_submitted"])
    assert len(saved.fields_submitted) == 2
    assert saved.fields_submitted[0].label == "Full name *"

    saved = save_attachments(app.id, RECARE_FIXTURE["attachments"])
    assert [a.to_dict() for a in saved.attachments] == RECARE_FIXTURE["attachments"]

    # Persisted, not just in-memory.
    reloaded = applications.get(app.id)
    assert reloaded.confirmation.confirmed_at == "2026-08-13T09:27:00+02:00"
    assert reloaded.screening.glassdoor.rating == 3.3
    assert reloaded.screening.glassdoor.reviews == 17
    assert len(reloaded.fields_submitted) == 2
    assert [a.to_dict() for a in reloaded.attachments] == RECARE_FIXTURE["attachments"]


def test_list_notes_from_a_jobs_record_flatten_to_one_string():
    """A migrated record's list-shaped `notes` must not reach the wire model.

    Eight records imported from Jobs carry `notes` as a list of separate notes.
    `Application.notes` and `ApplicationModel` both declare a plain string, and
    an unflattened list 500s GET /api/applications (and the analytics view that
    reads it), so from_dict coerces on the way in.
    """
    app = Application.from_dict(
        {
            "id": "31b806822964",
            "company": "Jimdo",
            "notes": [
                "Heading flag: FILTER BREACH, see Glassdoor below",
                "Status flag: Submitted in error: the company fails filter 5.",
            ],
        }
    )

    assert app.notes == (
        "Heading flag: FILTER BREACH, see Glassdoor below\n\n"
        "Status flag: Submitted in error: the company fails filter 5."
    )
    assert app.to_dict()["notes"] == app.notes


def test_notes_survive_every_other_shape_unchanged():
    """A plain string is untouched; absent/None notes stay the empty default."""
    assert Application.from_dict({"notes": "one note"}).notes == "one note"
    assert Application.from_dict({"notes": None}).notes == ""
    assert Application.from_dict({}).notes == ""
    assert Application.from_dict({"notes": ["", "  ", "kept"]}).notes == "kept"
