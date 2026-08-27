"""The cover letter as an uploadable file, for ATS forms that want a document.

An application that uploaded only the CV is half-finished: most ATS forms take
the letter as a second upload through the same control. These tests pin down
that the two tools carrying guardrail-vouched letter text also hand the agent a
path to upload, that a blocked letter never gets one, and that a missing
rendering backend degrades to "text only" instead of failing an application.
"""

from __future__ import annotations

import pytest

import coverletter.store as letters
import render.cover_letter as render_letter
import screening.store as store
from agenttools import letter_files, tools_letter
from agenttools.tools_ledger import get_approved_applications
from providers.fake import FakeProvider
from truth.model import Bullet, Experience, Skill, Truth
from truth.store import save as save_truth


@pytest.fixture
def fake_renderer(monkeypatch, data_dir):
    """Stand in for WeasyPrint, which is not installed in every environment.

    Writes a real file at the real destination so the tests assert on what the
    agent would actually find on the volume, and records the HTML it was handed
    so the letter's own text can be checked.
    """
    rendered = []

    def _render_pdf(html, filename="cv.pdf"):
        out = data_dir / filename
        out.write_bytes(b"%PDF-1.4 fake")
        rendered.append((filename, html))
        return out

    monkeypatch.setattr(render_letter, "render_pdf", _render_pdf)
    return rendered


def _seed_truth() -> None:
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
                        Bullet(
                            id="exp-acme-1-b1",
                            value="Built a payments API",
                            source="linkedin-pdf",
                        )
                    ],
                )
            ],
            education=[],
            skills=[Skill(id="skill-py-1", value="Python", source="linkedin-pdf")],
        )
    )


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


def test_generated_letter_comes_with_a_file_to_upload(data_dir, fake_renderer):
    _seed_truth()
    fake = FakeProvider(
        json_responses=[
            {"paragraphs": [{"text": "I worked at Acme Corp.", "claims": ["Acme Corp"]}]}
        ]
    )

    result = tools_letter.generate_cover_letter(
        "A posting", "Professional", "Short", provider=fake
    )

    assert result["blocked"] is False
    assert result["letter_path"] == str(data_dir / result["letter_asset_id"])
    assert (data_dir / result["letter_asset_id"]).exists()
    assert result["letter_download_url"] == f"/api/download/{result['letter_asset_id']}"
    # The file is a render of the letter that was actually returned, not of
    # some other text: uploading a document that disagrees with the submitted
    # text is exactly the failure the guardrail exists to prevent.
    _, html = fake_renderer[0]
    assert "I worked at Acme Corp." in html


def test_two_letters_do_not_share_a_file(data_dir, fake_renderer):
    """generate_cover_letter is stateless by design; naming the file after the
    letter's own text is what keeps N concurrent applications from uploading
    each other's letter."""
    _seed_truth()

    def _letter(marker, claim):
        return tools_letter.generate_cover_letter(
            "A posting",
            "Professional",
            "Short",
            provider=FakeProvider(
                json_responses=[{"paragraphs": [{"text": marker, "claims": [claim]}]}]
            ),
        )

    a = _letter("I worked at Acme Corp.", "Acme Corp")
    b = _letter("I use Python daily.", "Python")

    assert a["letter_asset_id"] != b["letter_asset_id"]


def test_blocked_letter_is_never_rendered(data_dir, fake_renderer):
    """A file is an upload. Rendering text the guardrail refused would put an
    ungrounded claim in front of an employer through the back door."""
    _seed_truth()
    fake = FakeProvider(
        json_responses=[
            {"paragraphs": [{"text": "I led a 400-person org.", "claims": ["400-person org"]}]}
        ]
    )

    result = tools_letter.generate_cover_letter(
        "A posting", "Professional", "Short", provider=fake
    )

    assert result["blocked"] is True
    assert result["letter_path"] is None
    assert result["letter_asset_id"] is None
    assert fake_renderer == []


def test_blocked_company_returns_no_file(data_dir, fake_renderer):
    import agentconfig.store as agentconfig

    cfg = agentconfig.load()
    cfg.blocked_companies = ["Contoso Labs"]
    agentconfig.save(cfg)

    result = tools_letter.generate_cover_letter(
        "A posting", "Professional", "Short", company="Contoso Labs"
    )

    assert result["blocked_reason"] == "company_blocked"
    assert result["letter_path"] is None
    assert fake_renderer == []


def test_approved_item_carries_a_letter_file(data_dir, fake_renderer):
    s = _approved_with_letter(text="My own words.", source="operator")

    item = get_approved_applications()[0]

    assert item["blocked_reason"] == ""
    assert item["cover_letter_asset_id"] == f"cover_letter_screening_{s.id}.pdf"
    assert item["cover_letter_path"] == str(letters.pdf_path(s.id))
    assert letters.pdf_path(s.id).exists()
    _, html = fake_renderer[0]
    assert "My own words." in html


def test_approved_item_reuses_an_up_to_date_render(data_dir, fake_renderer):
    """A queue read must not pay for a render per approved item per run."""
    _approved_with_letter()

    get_approved_applications()
    get_approved_applications()

    assert len(fake_renderer) == 1


def test_edited_letter_is_re_rendered(data_dir, fake_renderer):
    """A stale PDF would upload text the operator has already replaced."""
    s = _approved_with_letter(text="First draft.")
    get_approved_applications()

    letters.save(s.id, letters.CoverLetterDraft(text="Second draft.", source="operator"))
    get_approved_applications()

    assert len(fake_renderer) == 2
    assert "Second draft." in fake_renderer[1][1]


def test_blocked_item_gets_no_file(data_dir, fake_renderer):
    """A blocked item is reported, never applied to."""
    s = _approved_with_letter()
    letters.save(s.id, letters.CoverLetterDraft(text="   "))

    item = get_approved_applications()[0]

    assert item["blocked_reason"] == "no_letter"
    assert item["cover_letter_path"] is None
    assert fake_renderer == []


def test_deleting_a_draft_removes_its_rendered_file(data_dir, fake_renderer):
    """Otherwise a later run uploads a letter whose text no longer exists."""
    s = _approved_with_letter()
    get_approved_applications()
    assert letters.pdf_path(s.id).exists()

    assert letters.delete(s.id) is True

    assert not letters.pdf_path(s.id).exists()


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


def test_letter_file_is_never_written_outside_the_volume(data_dir):
    """The screening id reaches the filename builder from stored state; a
    traversal in it must not steer a write out of the data directory."""
    with pytest.raises(ValueError):
        letters.pdf_filename("../escape")
    assert (
        letter_files.render_screening_letter("../escape", "hi", "")
        == letter_files.NO_FILE
    )
