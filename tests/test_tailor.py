"""Tailor Engine golden invariant: the draft references only truth ids, and any
non-truth claim surfaces as an Inference, never in the draft."""

from __future__ import annotations

from providers.fake import FakeProvider
from truth.model import Bullet, Experience, Skill, Truth
from tailor import tailor, claims_for_ids


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
                    Bullet(
                        id="exp-acme-1-b1",
                        value="Built a payments API in Python",
                        source="linkedin-pdf",
                    )
                ],
            )
        ],
        education=[],
        skills=[Skill(id="skill-py-1", value="Python", source="linkedin-pdf")],
    )


def _router(system, messages, schema):
    """Route each provider call by the schema it was given."""
    props = (schema or {}).get("properties", {})
    if "keywords" in props:
        return {"keywords": ["Python", "Kubernetes"]}
    if "inferences" in props:
        return {
            "inferences": [
                {
                    "claim": "Experience with Kubernetes",
                    "rationale": "Posting requires it",
                    "experienceId": "exp-acme-1",
                }
            ]
        }
    if "experiences" in props:
        # Select/rephrase: reference real ids, plus one fabricated bullet id
        # that must be dropped by the invariant.
        return {
            "experiences": [
                {
                    "id": "exp-acme-1",
                    "bullets": [
                        {"id": "exp-acme-1-b1", "text": "Delivered a payments API in Python"},
                        {"id": "does-not-exist", "text": "Led a team of 200 engineers"},
                    ],
                }
            ],
            "skills": ["skill-py-1"],
        }
    return {}


def test_draft_references_only_truth_ids_and_flags_inference(data_dir):
    provider = FakeProvider(router=_router)
    truth = _truth()
    result = tailor("A backend role using Python and Kubernetes.", truth, provider)

    valid_ids = truth.all_ids()
    draft = result["draft"]

    # every draft experience references a REAL truth experience id
    assert all(e.source_id in valid_ids for e in draft.experiences)

    # the fabricated bullet (unknown id) was dropped; the real one was rephrased
    all_bullets = [b for e in draft.experiences for b in e.bullets]
    assert "Delivered a payments API in Python" in all_bullets
    assert "Led a team of 200 engineers" not in all_bullets

    # the non-truth claim surfaced as an Inference, not in the draft
    assert result["keywords"] == ["Python", "Kubernetes"]
    assert len(result["inferences"]) == 1
    assert result["inferences"][0]["claim"] == "Experience with Kubernetes"


def test_claims_for_ids_maps_approved_inferences(data_dir):
    provider = FakeProvider(router=_router)
    tailor("posting", _truth(), provider)
    # persisted draft's inference id is inf-1; maps to (experience_id, claim)
    assert claims_for_ids(["inf-1"]) == [("exp-acme-1", "Experience with Kubernetes")]
    assert claims_for_ids(["nope"]) == []


def test_empty_provider_falls_back_to_verbatim_truth(data_dir):
    provider = FakeProvider()  # returns schema-empty
    truth = _truth()
    result = tailor("posting", truth, provider)
    # fallback carries truth experiences verbatim, still only real ids
    assert {e.source_id for e in result["draft"].experiences} == {
        e.id for e in truth.experiences
    }
    assert result["draft"].skills == [s.value for s in truth.skills]
