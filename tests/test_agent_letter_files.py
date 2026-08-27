"""The cover letter as an uploadable file, for ATS forms that want a document.

An application that uploaded only the CV is half-finished: many ATS forms take
the letter as a second document. These tests pin down that the operator's
approved letter reaches the agent as a file, that a letter generated in-run
does NOT (the guardrail validates a paragraph's declared claims, never its
prose, so rendering there would turn an unchecked paragraph into a document),
that a file which exists is always a complete render of the text it is named
for, and that nothing here can fail a queue read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import coverletter.store as letters
import render.cover_letter as render_letter
import screening.store as store
from agenttools import letter_files
from agenttools.tools_ledger import get_approved_applications
from storage import data_dir as _data_dir


@pytest.fixture
def fake_renderer(monkeypatch, data_dir):
    """Stand in for WeasyPrint, which is not installed in every environment.

    Writes a real file at the real destination so the tests assert on what the
    agent would actually find on the volume, and records the HTML it was handed
    so the letter's own text can be checked.
    """
    rendered = []

    def _render_pdf(html, filename="cv.pdf"):
        out = _data_dir() / filename
        out.write_bytes(b"%PDF-1.4 fake")
        rendered.append((filename, html))
        return out

    monkeypatch.setattr(render_letter, "render_pdf", _render_pdf)
    return rendered


def _approved_with_letter(text="Dear team, I am applying.", source="generated"):
    s = store.create(
        {
            "company": "Contoso Labs",
            "role": "Staff",
            "url": "https://contoso.example/jobs/1",
            "verdict": "deferred",
        }
    )
    store.set_approval(s.id, "approved")
    letters.save(s.id, letters.CoverLetterDraft(text=text, source=source))
    return s


def _pdfs(data_dir):
    """Every file this feature can leave behind — renders and staging alike."""
    return sorted(p.name for p in data_dir.glob("*.pdf*"))


def test_approved_item_carries_a_letter_file(data_dir, fake_renderer):
    s = _approved_with_letter(text="My own words.", source="operator")

    item = get_approved_applications()[0]

    assert item["blocked_reason"] == ""
    assert item["cover_letter_asset_id"] == letters.pdf_filename(s.id, "My own words.")
    assert item["cover_letter_path"] == str(letters.pdf_path(s.id, "My own words."))
    assert letters.pdf_path(s.id, "My own words.").exists()
    _, html = fake_renderer[0]
    assert "My own words." in html


def test_generated_letters_are_never_rendered(data_dir, fake_renderer):
    """`generate_cover_letter` takes caller-supplied `paragraphs` and the
    guardrail only validates each paragraph's declared `claims`, never its
    prose — so a paragraph with an empty claims list passes. Rendering there
    would turn text the guardrail never checked into a document an employer
    receives as vouched-for. It must stay text."""
    from agenttools import tools_letter
    from providers.fake import FakeProvider
    from truth.model import Bullet, Experience, Skill, Truth
    from truth.store import save as save_truth

    save_truth(
        Truth(
            experiences=[
                Experience(
                    id="exp-acme-1",
                    role="Senior Engineer",
                    company="Acme Corp",
                    start="2020",
                    end="2023",
                    source="linkedin-pdf",
                    bullets=[
                        Bullet(id="exp-acme-1-b1", value="Built an API", source="linkedin-pdf")
                    ],
                )
            ],
            education=[],
            skills=[Skill(id="skill-py-1", value="Python", source="linkedin-pdf")],
        )
    )

    result = tools_letter.generate_cover_letter(
        "A posting",
        "Professional",
        "Short",
        # The bypass shape: prose the guardrail never sees, because it declares
        # no claims. It passes validation and must still produce no file.
        paragraphs=[{"text": "I led a 400-person org at NASA.", "claims": []}],
        provider=FakeProvider(json_responses=[{"paragraphs": []}]),
    )

    assert result["blocked"] is False
    assert "400-person org" in result["text"]
    assert "letter_path" not in result
    assert fake_renderer == []
    assert _pdfs(data_dir) == []


def test_editing_the_letter_renders_a_new_file_and_sweeps_the_old(
    data_dir, fake_renderer
):
    """The name carries a digest of the text, so an edit cannot overwrite a
    good render. The superseded file is then swept: nothing dereferences it —
    an application records the filenames it read off the employer's form, not
    a path on this volume — so left alone it would accumulate one copy of the
    operator's private letter per edit, forever."""
    s = _approved_with_letter(text="First draft.")
    first = get_approved_applications()[0]["cover_letter_path"]

    letters.save(s.id, letters.CoverLetterDraft(text="Second draft.", source="operator"))
    second = get_approved_applications()[0]["cover_letter_path"]

    assert first != second
    assert "Second draft." in fake_renderer[1][1]
    assert _pdfs(data_dir) == [Path(second).name]


def test_deleting_a_draft_sweeps_every_render_of_it(data_dir, fake_renderer):
    s = _approved_with_letter(text="First draft.")
    get_approved_applications()
    letters.save(s.id, letters.CoverLetterDraft(text="Second draft."))
    get_approved_applications()

    assert letters.delete(s.id) is True

    assert _pdfs(data_dir) == []


def test_an_identical_letter_is_not_re_rendered(data_dir, fake_renderer):
    """A queue read must not pay for a render per approved item per run."""
    _approved_with_letter()

    get_approved_applications()
    get_approved_applications()

    assert len(fake_renderer) == 1


def test_a_reverted_edit_renders_again_under_its_own_name(data_dir, fake_renderer):
    """Content addressing, not timestamps: reverted text renders to the name
    it had before, and is served from there whatever the draft's mtime says."""
    s = _approved_with_letter(text="First draft.")
    original = get_approved_applications()[0]["cover_letter_path"]
    letters.save(s.id, letters.CoverLetterDraft(text="Second draft."))
    get_approved_applications()

    letters.save(s.id, letters.CoverLetterDraft(text="First draft."))
    item = get_approved_applications()[0]

    assert item["cover_letter_path"] == original
    assert _pdfs(data_dir) == [Path(original).name]


def test_a_failed_render_leaves_no_file_to_mistake_for_one(data_dir, monkeypatch):
    """The renderer writes straight through to its destination, so a failure
    part-way leaves a truncated file. Staged writes mean the destination either
    does not exist or is a complete render — otherwise the next run would find
    a stump, treat it as done, and upload it to an employer."""
    s = _approved_with_letter()

    def _truncate_then_die(html, filename="cv.pdf"):
        out = _data_dir() / filename
        out.write_bytes(b"%PDF-1.4 trunc")
        raise RuntimeError("renderer died mid-write")

    monkeypatch.setattr(render_letter, "render_pdf", _truncate_then_die)

    first = get_approved_applications()[0]
    assert first["cover_letter_path"] is None
    assert not letters.pdf_path(s.id, first["cover_letter"]).exists()
    assert _pdfs(data_dir) == []

    # And the next run, with a healthy backend, still renders.
    rendered = []

    def _ok(html, filename="cv.pdf"):
        out = _data_dir() / filename
        out.write_bytes(b"%PDF-1.4 fake")
        rendered.append(filename)
        return out

    monkeypatch.setattr(render_letter, "render_pdf", _ok)
    assert get_approved_applications()[0]["cover_letter_path"] is not None
    assert len(rendered) == 1


def test_blocked_item_gets_no_file(data_dir, fake_renderer):
    """A blocked item is reported, never applied to."""
    s = _approved_with_letter()
    letters.save(s.id, letters.CoverLetterDraft(text="   "))

    item = get_approved_applications()[0]

    assert item["blocked_reason"] == "no_letter"
    assert item["cover_letter_path"] is None
    assert fake_renderer == []


def test_no_rendering_backend_degrades_to_text_only(data_dir, monkeypatch):
    """WeasyPrint is optional. A missing backend means "no file to upload" —
    never a failed application."""
    from render.pdf import RenderUnavailable

    def _unavailable(html, filename="cv.pdf"):
        raise RenderUnavailable("WeasyPrint not available")

    monkeypatch.setattr(render_letter, "render_pdf", _unavailable)
    _approved_with_letter()

    item = get_approved_applications()[0]

    assert item["blocked_reason"] == ""
    assert item["cover_letter"] == "Dear team, I am applying."
    assert item["cover_letter_path"] is None
    assert item["cover_letter_asset_id"] is None


def test_an_unreadable_truth_store_does_not_fail_the_queue(data_dir, fake_renderer):
    """Rendering reads the truth store for the letter's header. Before this
    feature the approved queue never touched that file, and a raise here would
    strand every item the run had already claimed on a 900s lease."""
    _approved_with_letter()

    def _boom():
        raise ValueError("Duplicate truth id: 's1'")

    import agenttools.letter_files as lf

    original = lf.load_truth
    lf.load_truth = _boom
    try:
        item = get_approved_applications()[0]
    finally:
        lf.load_truth = original

    assert item["blocked_reason"] == ""
    assert item["cover_letter"] == "Dear team, I am applying."
    assert item["cover_letter_path"] is None


def test_letter_file_is_never_written_outside_the_volume(data_dir, fake_renderer):
    """The screening id reaches the filename builder from stored state; a
    traversal in it must not steer a write out of the data directory."""
    with pytest.raises(ValueError):
        letters.pdf_filename("../escape", "hi")

    assert letter_files.render_screening_letter("../escape", "hi") == letter_files.NO_FILE
    assert fake_renderer == []
    assert not (data_dir.parent / "escape").exists()


def test_two_concurrent_renders_both_produce_a_file(data_dir, monkeypatch):
    """`storage/atomic.py` records what a shared staging name costs: whichever
    writer renames second finds the source already gone. A queue read with no
    run_id claims nothing, so two overlapping runs can render the same letter
    at the same moment — and a run that rendered successfully must not be told
    there is no file. Each write gets its own staging name."""
    import threading

    start = threading.Barrier(2)

    def _slow_render(html, filename="cv.pdf"):
        out = _data_dir() / filename
        out.write_bytes(b"%PDF-1.4 fake")
        start.wait(timeout=5)
        return out

    monkeypatch.setattr(render_letter, "render_pdf", _slow_render)
    results: list[dict] = []

    def _render():
        results.append(letter_files.render_screening_letter("s1", "Shared text."))

    threads = [threading.Thread(target=_render) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2
    assert all(r["path"] for r in results), "a completed render reported no file"
    assert _pdfs(data_dir) == [letters.pdf_filename("s1", "Shared text.")]
