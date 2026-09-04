"""Cover-letter generation: truthful passes, fabricated claims block."""

from __future__ import annotations

from coverletter.generate import build_letter, load_letter_draft, save_letter_draft
from providers.fake import FakeProvider
from truth.answers import Answers
from truth.model import Bullet, Experience, Hobby, Profile, Skill, Truth


def _truth() -> Truth:
    return Truth(
        experiences=[
            Experience(
                id="exp-acme-1",
                role="Senior Software Engineer",
                company="Acme Corp",
                start="2020",
                end="2023",
                source="linkedin-pdf",
                bullets=[
                    Bullet(id="exp-acme-1-b1", value="Built a payments API", source="linkedin-pdf")
                ],
            )
        ],
        education=[],
        skills=[Skill(id="skill-py-1", value="Python", source="linkedin-pdf")],
    )


def _router_ok(system, messages, schema):
    return {
        "paragraphs": [
            {"text": "I am excited to apply for this role.", "claims": []},
            {
                "text": "As a Senior Software Engineer at Acme Corp, I use Python daily.",
                "claims": ["Senior Software Engineer", "Acme Corp", "Python"],
            },
        ]
    }


def _router_lie(system, messages, schema):
    return {
        "paragraphs": [
            {"text": "I led a team of 200 at Globex.", "claims": ["Led a team of 200 at Globex"]}
        ]
    }


def test_truthful_letter_passes(data_dir):
    out = build_letter("A Python role", "Professional", "Short", _truth(), FakeProvider(router=_router_ok))
    assert out["blocked"] is False
    assert "Acme Corp" in out["text"]
    assert "excited to apply" in out["text"]


def test_fabricated_claim_blocks(data_dir):
    out = build_letter("A role", "Professional", "Short", _truth(), FakeProvider(router=_router_lie))
    assert out["blocked"] is True
    assert out["text"] == ""
    assert any(tok in out["unverifiable"] for tok in ("200", "globex"))


def test_blocked_letter_groups_claims_by_source_text(data_dir):
    """A block now surfaces whole-claim sentences, not just loose tokens, so the
    UI can offer per-claim approve/decline."""
    out = build_letter("A role", "Professional", "Short", _truth(), FakeProvider(router=_router_lie))
    assert out["blocked"] is True
    claims = out["blocked_claims"]
    assert len(claims) == 1
    claim = claims[0]
    assert claim.text == "Led a team of 200 at Globex"
    assert any(t in claim.tokens for t in ("200", "globex"))


def test_approving_blocked_claim_unblocks_without_truth_write(data_dir):
    """Approving the exact blocked claim text lets it pass for THIS generation
    (added to allowed), and it is never persisted to the truth file."""
    from truth import load

    blocked = build_letter("A role", "Professional", "Short", _truth(), FakeProvider(router=_router_lie))
    approved = {c.text for c in blocked["blocked_claims"]}

    out = build_letter(
        "A role", "Professional", "Short", _truth(), FakeProvider(router=_router_lie),
        approved_texts=approved,
    )
    assert out["blocked"] is False
    assert "Globex" in out["text"]
    # Nothing was written to truth: no Globex experience appears in the store.
    assert all(e.company != "Globex" for e in load().experiences)


def test_denied_claim_is_dropped_from_letter(data_dir):
    """A denied claim's whole paragraph is excised before validation, so a
    letter whose only factual claim is denied has nothing left to trip the
    guardrail, and the denied claim's text is entirely absent from the
    rendered letter."""
    out = build_letter(
        "A role", "Professional", "Short", _truth(), FakeProvider(router=_router_lie),
        denied_texts={"Led a team of 200 at Globex"},
    )
    assert out["blocked"] is False
    assert "Led a team of 200 at Globex" not in out["text"]
    assert "Globex" not in out["text"]


def test_denied_claim_empties_letter_when_it_is_the_only_paragraph(data_dir):
    """When the letter consists of a single paragraph and its only claim is
    denied, excising that paragraph leaves nothing behind: the letter text is
    empty even though the guardrail itself did not block."""
    out = build_letter(
        "A role", "Professional", "Short", _truth(), FakeProvider(router=_router_lie),
        denied_texts={"Led a team of 200 at Globex"},
    )
    assert out["blocked"] is False
    assert out["text"] == ""


def test_hobby_value_passes_guardrail(data_dir):
    """A letter mentioning a hobby value from the truth file passes the guardrail."""
    def _router_hobby_claim(system, messages, schema):
        return {
            "paragraphs": [
                {
                    "text": "Outside of work, I enjoy playing Chess and building projects.",
                    "claims": ["Chess"],
                }
            ]
        }

    truth = Truth(
        experiences=[],
        education=[],
        skills=[],
        hobbies=[Hobby(id="h-chess", value="Chess", source="user-confirmed")],
    )
    out = build_letter("A role", "Professional", "Short", truth, FakeProvider(router=_router_hobby_claim))
    assert out["blocked"] is False
    assert "Chess" in out["text"]


def test_profile_header_is_allowed_claim_source(data_dir):
    """A letter claiming the profile summary text is not blocked, proving the
    Review-page profile is now an allowed claim source."""
    truth = Truth(
        profile=Profile(
            name="Alice Engineer",
            email="alice@example.com",
            phone="+1 555-0123",
            location="San Francisco, CA",
            summary="Experienced software engineer focused on backend systems.",
        ),
        experiences=[],
        skills=[],
    )

    def router_profile_claim(system, messages, schema):
        return {
            "paragraphs": [
                {
                    "text": "I am an experienced software engineer focused on backend systems.",
                    "claims": ["experienced software engineer focused on backend systems"],
                }
            ]
        }

    out = build_letter("A role", "Professional", "Short", truth, FakeProvider(router=router_profile_claim))
    assert out["blocked"] is False
    assert "experienced software engineer" in out["text"]


def test_answers_block_without_parameter_unblock_with_parameter(data_dir):
    """A letter claiming a value that exists only in truth.answers.Answers is
    blocked without answers=, and unblocked when answers= carries it."""
    truth = _truth()
    answers = Answers(current_role="Staff Engineer")

    def router_answer_claim(system, messages, schema):
        return {
            "paragraphs": [
                {
                    "text": "I currently work as a Staff Engineer.",
                    "claims": ["Staff Engineer"],
                }
            ]
        }

    # Without answers: blocked
    out_no_answers = build_letter(
        "A role", "Professional", "Short", truth, FakeProvider(router=router_answer_claim)
    )
    assert out_no_answers["blocked"] is True

    # With answers: unblocked
    out_with_answers = build_letter(
        "A role", "Professional", "Short", truth, FakeProvider(router=router_answer_claim),
        answers=answers
    )
    assert out_with_answers["blocked"] is False
    assert "Staff Engineer" in out_with_answers["text"]


def test_canonical_cv_asset_id_never_allowed(data_dir):
    """A paragraph claiming the canonical_cv_asset_id value stays blocked even
    when answers= carries it, since it is an internal asset UUID, not a claim."""
    truth = _truth()
    answers = Answers(canonical_cv_asset_id="cv-12345")

    def router_asset_claim(system, messages, schema):
        return {
            "paragraphs": [
                {
                    "text": "My CV is cv-12345.",
                    "claims": ["cv-12345"],
                }
            ]
        }

    out = build_letter(
        "A role", "Professional", "Short", truth, FakeProvider(router=router_asset_claim),
        answers=answers
    )
    assert out["blocked"] is True
    assert "cv-12345" in out["unverifiable"]


def test_letter_draft_not_reused_across_postings(data_dir):
    """A draft cached for one posting is never returned for a different one."""
    paragraphs = [{"text": "Some letter text.", "claims": []}]
    save_letter_draft(paragraphs, "posting A")
    assert load_letter_draft("posting B") is None


def test_letter_draft_reused_for_same_posting(data_dir):
    """A draft cached for a posting is returned when reloaded for that same
    posting."""
    paragraphs = [{"text": "Some letter text.", "claims": []}]
    save_letter_draft(paragraphs, "posting A")
    assert load_letter_draft("posting A") == paragraphs


def test_legacy_bare_list_draft_is_treated_as_stale(data_dir):
    """A cover_letter_draft.json written before posting-binding (a bare JSON
    list, with no postingHash envelope) is stale and forces regeneration
    rather than being returned as-is."""
    from coverletter.generate import _letter_draft_path
    import json

    p = _letter_draft_path()
    p.write_text(json.dumps([{"text": "Old letter.", "claims": []}]), encoding="utf-8")
    assert load_letter_draft("posting A") is None
