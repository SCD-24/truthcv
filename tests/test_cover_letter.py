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
