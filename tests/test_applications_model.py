"""Application model: legacy defaults and full nested-evidence shapes.

The nested-evidence fixture preserves the exact shape of a real Jobs
applications/records/*.json entry — the nesting, field population, and
evidence sub-objects a migrated record actually has — so the evidence
dataclasses (Confirmation, Screening/Glassdoor, FieldSubmitted, Attachment) are
exercised against a real production record shape, with all identifying values
replaced by placeholders rather than invented from scratch.
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
        "company": "Hooli",
        "submitted": True,
        "submission_type": "General",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    app = Application.from_dict(legacy)
    assert app.company == "Hooli"
    assert app.submitted is True
    assert app.fields_submitted == []
    assert app.confirmation == Confirmation()
    assert app.screening == Screening()
    assert app.attachments == []
    assert app.cv_document is None
    assert app.cover_letter_document is None


# --- Full nested evidence shape, real Jobs-shaped fixture ------------------

# Values below preserve the exact shape of a real migrated Jobs applications
# record — the nesting, field population, and evidence sub-objects
# (confirmation.confirmed_at/evidence and screening.glassdoor's numeric
# rating, reviews and waiver_applied in particular) — with every identifying
# value (company, URLs, candidate name, CV filename, Glassdoor profile ids)
# replaced by placeholders, so the round trip is checked against a real
# evidence shape, not an invented one.
NORTHWIND_FIXTURE = {
    "id": "a1b2c3d4e5f6",
    "company": "Northwind Health GmbH",
    "website": "https://northwind-health.example",
    "application_url": "https://careers.northwind-health.example/o/ai-ml-engineer-mwd",
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
            "https://careers.northwind-health.example/o/ai-ml-engineer-mwd/applied "
            "and the Application tab relabelled itself \"Application \u2014 Applied\"."
        ),
    },
    "screening": {
        "entity": (
            "Northwind Health GmbH, Musterstra\u00dfe 1, 10115 Berlin \u2014 "
            "HRB 100000 B, Amtsgericht Charlottenburg (Berlin), managing director "
            "Erika Mustermann, read off Northwind's own Impressum."
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
                "not from a search snippet (the Stark rule). Profile "
                "**E1000001**, identified as the right company by four "
                "independent markers on that page: HQ **Berlin, Deutschland**, "
                "founded **2017**, CEO **Erika Mustermann** (the same person "
                "named as managing director in the Impressum), and website "
                "**northwind-health.example**. Rating **3,3 \u2605**. The page reports "
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
                "named \"Northwind\" exists (E1000002, 3.1\u2605, 5 reviews) and is "
                "also under 20 reviews, so the waiver holds on either profile."
            ),
        },
    },
    "attachments": [
        {"kind": "cv", "path": "2026_Ada_Example_CV_v2.pdf"},
        {"kind": "cover_letter", "path": "scratchpad/northwind_cover.pdf"},
    ],
    "cv_document": None,
    "cover_letter_document": None,
    "created_at": "2026-08-13T07:27:00+00:00",
    "updated_at": "2026-08-13T07:27:00+00:00",
}


def test_full_nested_evidence_shape_exact_round_trip():
    app = Application.from_dict(NORTHWIND_FIXTURE)

    # Confirmation evidence matches the real record exactly (hard-coded here,
    # not read back off the fixture, so a typo in either place cannot hide).
    assert app.confirmation.text == (
        "All done! Your application has been successfully submitted!"
    )
    assert app.confirmation.confirmed_at == "2026-08-13T09:27:00+02:00"
    assert app.confirmation.evidence == (
        "Page navigated to "
        "https://careers.northwind-health.example/o/ai-ml-engineer-mwd/applied "
        "and the Application tab relabelled itself \"Application \u2014 Applied\"."
    )

    # Glassdoor numeric data matches the real record exactly.
    assert app.screening.glassdoor.rating == 3.3
    assert app.screening.glassdoor.reviews == 17
    assert app.screening.glassdoor.waiver_applied is True

    # Whole-record round trip is exact. The fixture is a real legacy record and
    # so carries no "profile" or "screening_id" key; to_dict always emits them,
    # each defaulted to "" (profile is pinned by
    # test_legacy_record_without_profile_loads_default). Spelling the delta out
    # here keeps the fixture faithful to what is actually on disk.
    assert app.to_dict() == {**NORTHWIND_FIXTURE, "profile": "", "screening_id": ""}


# --- Generic editable writes refuse structured fields; setters persist them -

def test_create_and_update_ignore_structured_fields(data_dir):
    app = applications.create(
        {
            "company": "Northwind Health GmbH",
            "status": "confirmed",
            # Structured/nested fields are not in Application.EDITABLE and
            # must be silently ignored by the generic create path.
            "confirmation": NORTHWIND_FIXTURE["confirmation"],
            "screening": NORTHWIND_FIXTURE["screening"],
            "fields_submitted": NORTHWIND_FIXTURE["fields_submitted"],
            "attachments": NORTHWIND_FIXTURE["attachments"],
        }
    )
    assert app.company == "Northwind Health GmbH"
    assert app.status == "confirmed"
    assert app.confirmation == Confirmation()
    assert app.screening == Screening()
    assert app.fields_submitted == []
    assert app.attachments == []

    updated = applications.update(
        app.id,
        {
            "notes": "Updated notes",
            "confirmation": NORTHWIND_FIXTURE["confirmation"],
            "screening": NORTHWIND_FIXTURE["screening"],
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
    app = applications.create({"company": "Northwind Health GmbH"})

    saved = save_confirmation(app.id, NORTHWIND_FIXTURE["confirmation"])
    assert saved.confirmation.confirmed_at == "2026-08-13T09:27:00+02:00"
    assert saved.confirmation.evidence == NORTHWIND_FIXTURE["confirmation"]["evidence"]

    saved = save_screening(app.id, NORTHWIND_FIXTURE["screening"])
    assert saved.screening.glassdoor.rating == 3.3
    assert saved.screening.glassdoor.reviews == 17
    assert saved.screening.glassdoor.waiver_applied is True

    saved = save_fields_submitted(app.id, NORTHWIND_FIXTURE["fields_submitted"])
    assert len(saved.fields_submitted) == 2
    assert saved.fields_submitted[0].label == "Full name *"

    saved = save_attachments(app.id, NORTHWIND_FIXTURE["attachments"])
    assert [a.to_dict() for a in saved.attachments] == NORTHWIND_FIXTURE["attachments"]

    # Persisted, not just in-memory.
    reloaded = applications.get(app.id)
    assert reloaded.confirmation.confirmed_at == "2026-08-13T09:27:00+02:00"
    assert reloaded.screening.glassdoor.rating == 3.3
    assert reloaded.screening.glassdoor.reviews == 17
    assert len(reloaded.fields_submitted) == 2
    assert [a.to_dict() for a in reloaded.attachments] == NORTHWIND_FIXTURE["attachments"]


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
            "company": "Stark",
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


def test_profile_round_trip():
    app = Application(id="test-id", company="Test Co", profile="Senior Python")
    serialized = app.to_dict()
    assert serialized["profile"] == "Senior Python"
    deserialized = Application.from_dict(serialized)
    assert deserialized.profile == "Senior Python"
    assert deserialized.to_dict() == serialized


def test_legacy_record_without_profile_loads_default():
    raw = {"id": "test-id", "company": "Test Co", "submitted": True}
    app = Application.from_dict(raw)
    assert app.profile == ""
    assert app.company == "Test Co"
