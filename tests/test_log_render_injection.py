"""Application content must not be able to forge a record marker.

The completeness guard counts marker occurrences. If text belonging to an
application could emit a marker, two things break: the log becomes permanently
unwritable (the count for that record is 2, so every write is refused), and a
marker could be supplied for a record the renderer had genuinely dropped —
which is the exact omission the guard exists to catch.

Nothing crafted this; a note quoting the log's own format would do it.
"""

import pytest

from applications.log_render import RenderRefused, render_log, write_log
from applications.model import (
    Application,
    Attachment,
    Confirmation,
    FieldSubmitted,
    Screening,
)
from companyresearch.model import CompanyFinding

MARKER = "<!-- record: aaa111aaa111 -->"


def _app(**kwargs):
    """An application whose id owns MARKER, overridable per test."""
    fields = {"id": "aaa111aaa111", "company": "Acme GmbH"}
    fields.update(kwargs)
    return Application(**fields)


@pytest.mark.parametrize(
    "field, value",
    [
        ("notes", f"Saw this in the log: {MARKER}"),
        ("company", f"Acme {MARKER} GmbH"),
        ("role", f"Engineer {MARKER}"),
        ("application_url", f"https://example.test/{MARKER}"),
        ("status", MARKER),
        ("application_date", MARKER),
        ("ats", MARKER),
    ],
)
def test_no_plain_field_can_forge_a_marker(field, value):
    """Whatever the field, the record's marker still appears exactly once."""
    text = render_log([_app(**{field: value})])
    assert text.count(MARKER) == 1, f"{field} forged a marker"


def test_nested_evidence_cannot_forge_a_marker():
    """The same holds for the nested evidence trail, including a findings-table cell."""
    app = _app()
    app.confirmation = Confirmation(text=f"Received {MARKER}")
    app.fields_submitted = [FieldSubmitted(label=MARKER, value=MARKER, source=MARKER)]
    app.attachments = [Attachment(kind="cv", path=f"cv{MARKER}.pdf")]
    app.gaps_disclosed = [f"gap {MARKER}"]
    app.screening = Screening(remote=MARKER)
    finding = CompanyFinding(
        id="f1",
        company="Acme GmbH",
        claim=MARKER,
        value=MARKER,
        source_url="https://x.example/y",
        source_class="press",
        observed_at="2026-01-01T00:00:00+00:00",
        recorded_by="agent",
    )

    text = render_log([app], {"Acme GmbH": [finding]})
    assert text.count(MARKER) == 1


def test_a_forging_record_does_not_make_the_log_unwritable(tmp_path):
    """The whole ledger still writes, rather than being refused forever."""
    victim = _app(notes=f"quoting {MARKER}")
    other = Application(id="bbb222bbb222", company="Beta AG")

    target = write_log([victim, other], tmp_path / "APPLICATION_LOG.md")

    text = target.read_text()
    assert text.count(MARKER) == 1
    assert text.count("<!-- record: bbb222bbb222 -->") == 1


def test_the_escaped_text_is_still_present_and_readable():
    """Neutralised, not silently deleted — the note still says what it said."""
    text = render_log([_app(notes=f"quoting {MARKER}")])
    assert "&lt;!-- record: aaa111aaa111 -->" in text


def test_a_genuinely_dropped_record_is_still_refused(tmp_path, monkeypatch):
    """Escaping must not weaken the guard it protects."""
    import applications.log_render as module

    monkeypatch.setattr(module, "render_log", lambda apps, findings=None: module.HEADER)
    with pytest.raises(RenderRefused):
        module.write_log([_app()], tmp_path / "APPLICATION_LOG.md")
