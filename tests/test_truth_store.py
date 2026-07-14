"""Truth Store: model persistence, source-hash tracking, extraction, write-back."""

from __future__ import annotations

import pytest

from providers.fake import FakeProvider
from truth import (
    Bullet,
    Experience,
    Link,
    Profile,
    Skill,
    Truth,
    load,
    loaded_source_hash,
    persist_source_hash,
    save,
    validate,
)
from truth import extract


def _truth() -> Truth:
    return Truth(
        experiences=[
            Experience(
                id="exp-1",
                role="Engineer",
                company="Acme",
                start="2020",
                end="Present",
                source="linkedin-pdf",
                bullets=[Bullet("exp-1-b-1", "Shipped the thing", "linkedin-pdf")],
            )
        ],
        skills=[Skill("sk-python", "Python", "linkedin-pdf")],
    )


def test_save_load_round_trip(data_dir):
    save(_truth())
    assert load().to_dict() == _truth().to_dict()


def test_profile_round_trips(data_dir):
    t = _truth()
    t.profile = Profile(
        name="Jane Doe",
        email="jane@example.com",
        phone="+1 555 0100",
        location="Berlin",
        links=[Link("LinkedIn", "https://linkedin.com/in/jane")],
        summary="Backend engineer who ships",
    )
    save(t)
    loaded = load()
    assert loaded.profile.to_dict() == t.profile.to_dict()
    # A profile-only doc still loads (isn't discarded by the non-empty guard).
    save(Truth(profile=Profile(name="Solo")))
    assert load().profile.name == "Solo"


def test_profile_defaults_empty_when_absent(data_dir):
    # Legacy doc with no "profile" key loads a blank profile, not a crash.
    save(_truth())  # _truth() carries a default (empty) profile
    assert load().profile == Profile()


def test_load_empty_when_no_file(data_dir):
    assert load().is_empty()


def test_load_empty_on_pre_migration_flat_shape(data_dir, tmp_path):
    from truth.store import truth_path

    truth_path().write_text("entries:\n  - id: x\n", encoding="utf-8")
    assert load().is_empty()


def test_validate_rejects_bad_source():
    bad = Truth(skills=[Skill("sk-x", "X", "made-up")])
    with pytest.raises(ValueError):
        validate(bad)


def test_validate_rejects_duplicate_ids():
    dup = Truth(
        skills=[Skill("dup", "A", "linkedin-pdf"), Skill("dup", "B", "linkedin-pdf")]
    )
    with pytest.raises(ValueError):
        validate(dup)


def test_validate_rejects_empty_id():
    with pytest.raises(ValueError):
        validate(Truth(skills=[Skill("", "A", "linkedin-pdf")]))


def test_source_hash_round_trips(data_dir):
    assert loaded_source_hash() is None
    persist_source_hash("some profile text")
    assert loaded_source_hash() is not None


def test_source_hash_stable_across_whitespace(data_dir):
    persist_source_hash("hello   world\n\ndone")
    first = loaded_source_hash()
    persist_source_hash("hello world done")
    assert loaded_source_hash() == first  # whitespace-normalized


def test_source_hash_differs_for_different_text(data_dir):
    persist_source_hash("profile A")
    a = loaded_source_hash()
    persist_source_hash("profile B — a genuinely different resume")
    assert loaded_source_hash() != a


def test_extraction_tags_source_and_persists(data_dir):
    provider = FakeProvider(
        json_responses=[
            {
                "experiences": [
                    {
                        "role": "Software Engineer",
                        "company": "Acme",
                        "start": "2020",
                        "end": "Present",
                        "bullets": ["Led migration", "Led migration"],  # dup dropped
                    }
                ],
                "skills": ["Python", "Python"],  # dup dropped
                "profile": {
                    "name": "Jane Doe",
                    "email": "jane@example.com",
                    "location": "Berlin",
                    "links": [{"label": "LinkedIn", "url": "https://li/jane"}],
                    "summary": "Backend engineer",
                },
            }
        ]
    )
    truth = extract.build_truth_from_text("profile text", provider)
    assert [b.value for e in truth.experiences for b in e.bullets] == ["Led migration"]
    assert [s.value for s in truth.skills] == ["Python"]
    assert all(e.source == "linkedin-pdf" for e in truth.experiences)
    # profile extracted verbatim
    assert truth.profile.name == "Jane Doe"
    assert truth.profile.email == "jane@example.com"
    assert truth.profile.summary == "Backend engineer"
    assert [link.label for link in truth.profile.links] == ["LinkedIn"]
    # persisted to disk
    assert load().to_dict() == truth.to_dict()


def test_extraction_without_profile_is_blank(data_dir):
    provider = FakeProvider(
        json_responses=[
            {"experiences": [], "education": [], "skills": ["Go"]}  # no profile key
        ]
    )
    truth = extract.build_truth_from_text("profile text", provider)
    assert truth.profile == Profile()  # absent profile -> blank, no crash


def _extract_provider():
    return FakeProvider(
        json_responses=[
            {
                "experiences": [
                    {"role": "Engineer", "company": "Acme", "start": "2020", "bullets": []}
                ]
            }
        ]
    )


def test_extract_empty_store_calls_llm(data_dir):
    provider = _extract_provider()
    extract.build_truth_from_text("profile text", provider)
    assert len(provider.calls) == 1  # nothing cached -> LLM ran


def test_extract_same_source_reuses_without_llm(data_dir):
    text = "the same profile text"
    extract.build_truth_from_text(text, _extract_provider())  # populates + hashes
    second = FakeProvider(json_responses=[{"experiences": []}])
    result = extract.build_truth_from_text(text, second)
    assert second.calls == []  # cache hit -> no token spend
    assert not result.is_empty()  # returned the saved truth, not the empty response


def test_extract_new_source_reextracts(data_dir):
    extract.build_truth_from_text("first profile", _extract_provider())
    second = FakeProvider(
        json_responses=[
            {"experiences": [{"role": "Designer", "company": "Beta", "start": "2021", "bullets": []}]}
        ]
    )
    result = extract.build_truth_from_text("a completely different profile", second)
    assert len(second.calls) == 1  # different source hash -> LLM ran again
    assert result.experiences[0].role == "Designer"


def test_extract_text_garbage_raises_clean_error():
    from truth.pdf import PdfExtractError, extract_text

    with pytest.raises(PdfExtractError):
        extract_text(b"this is not a pdf at all")


def test_write_confirmed_tags_user_confirmed_and_dedups(data_dir):
    save(
        Truth(
            experiences=[
                Experience("exp-1", "Engineer", "Acme", "2020", "2022", "linkedin-pdf")
            ]
        )
    )
    result = extract.write_confirmed(
        [("exp-1", "Led migration to Kubernetes"), ("exp-1", "Led migration to Kubernetes")]
    )
    confirmed = [b for e in result.experiences for b in e.bullets if b.source == "user-confirmed"]
    assert len(confirmed) == 1
    assert confirmed[0].value == "Led migration to Kubernetes"
