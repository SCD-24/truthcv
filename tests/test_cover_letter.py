"""Cover-letter generation: truthful passes, fabricated claims block."""

from __future__ import annotations

from coverletter.generate import build_letter
from providers.fake import FakeProvider
from truth.model import Bullet, Experience, Skill, Truth


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
    """A denied claim is excluded from the validated texts, so a letter whose
    only factual claim is denied has nothing left to trip the guardrail."""
    out = build_letter(
        "A role", "Professional", "Short", _truth(), FakeProvider(router=_router_lie),
        denied_texts={"Led a team of 200 at Globex"},
    )
    assert out["blocked"] is False
