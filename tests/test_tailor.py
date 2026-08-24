"""Tailor Engine golden invariant: the draft references only truth ids, and any
non-truth claim surfaces as an Inference, never in the draft."""

from __future__ import annotations

import yaml

from providers.fake import FakeProvider
from truth.model import Bullet, Experience, Skill, Truth
from tailor import tailor, claims_for_ids
from tailor.keywords import extract_keywords, _is_junk_token
from tailor.infer import _uncovered_keywords, _infer_user_message


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
    result = tailor(
        "A backend role using Python and Kubernetes.", truth, lambda task=None: provider
    )

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
    tailor("posting", _truth(), lambda task=None: provider)
    # persisted draft's inference id is inf-1; maps to (experience_id, claim)
    assert claims_for_ids(["inf-1"]) == [("exp-acme-1", "Experience with Kubernetes")]
    assert claims_for_ids(["nope"]) == []


def test_junk_tokens_are_filtered_but_skills_kept():
    """Location/arrangement/title tokens are dropped; real skills survive."""
    assert _is_junk_token("Remote in Germany") is True
    assert _is_junk_token("Hybrid") is True
    assert _is_junk_token("Senior Data Engineer") is True
    assert _is_junk_token("Lead Engineer") is True
    # genuine skills must never be dropped
    assert _is_junk_token("ETL") is False
    assert _is_junk_token("Python") is False
    assert _is_junk_token("Distributed systems") is False


def test_extract_keywords_drops_junk(data_dir):
    """The junk filter runs inside extract_keywords, preserving skill order."""

    def router(system, messages, schema):
        return {"keywords": ["Senior Data Engineer", "ETL", "Remote in Germany", "Python"]}

    provider = FakeProvider(router=router)
    assert extract_keywords("some posting", provider) == ["ETL", "Python"]


def test_supplied_seniority_prefix_is_stripped(data_dir):
    """An operator-supplied seniority prefix filters titles like a built-in one.

    Without data/vocabulary/seniority_prefixes.txt the built-in ladder applies
    (existing behaviour); with one, its entries are merged in.
    """
    vocab_dir = data_dir / "vocabulary"
    vocab_dir.mkdir()
    (vocab_dir / "seniority_prefixes.txt").write_text(
        "# one prefix per line\nconsultant \nHead of", encoding="utf-8"
    )
    assert _is_junk_token("Consultant Paediatrician") is True
    assert _is_junk_token("head of nursing") is True  # built-ins still apply
    assert _is_junk_token("Paediatric nursing") is False


def test_supplied_arrangement_word_is_stripped(data_dir):
    """Operator-supplied arrangement words join the built-in junk filter."""
    vocab_dir = data_dir / "vocabulary"
    vocab_dir.mkdir()
    (vocab_dir / "arrangement_words.txt").write_text("teilzeit\nhomeoffice", encoding="utf-8")
    assert _is_junk_token("Teilzeit möglich") is True
    assert _is_junk_token("Homeoffice") is True
    assert _is_junk_token("Vollzeit") is False


def test_missing_vocabulary_files_mean_builtins_only(data_dir):
    """No vocabulary dir on the volume: today's exact filtering behaviour."""
    assert _is_junk_token("Senior Data Engineer") is True
    assert _is_junk_token("Remote in Germany") is True
    assert _is_junk_token("Kubernetes") is False


def test_uncovered_keywords_skips_facts_already_present():
    """Keywords already backed by truth are not re-proposed for inference."""
    existing = {"python", "built a payments api in python"}
    assert _uncovered_keywords(["Python", "Kubernetes"], existing) == ["Kubernetes"]


def test_infer_message_lists_keywords_and_falls_back_when_empty():
    """The inference message is keyword-driven, with a safe empty fallback."""
    truth = _truth()
    with_kw = _infer_user_message(["Kubernetes"], truth)
    assert "- Kubernetes" in with_kw
    assert "EACH posting keyword" in with_kw
    assert "(none extracted)" in _infer_user_message([], truth)


def test_unicode_names_tokenize_as_single_tokens():
    """Accented names/companies tokenize as one token, not shattered ASCII."""
    from guardrail.validate import _tokenize

    assert "müller" in _tokenize("Klaus Müller")
    assert _tokenize("Klaus Müller") == ["klaus", "müller"]
    assert _tokenize("Škoda Auto") == ["škoda", "auto"]


def test_guardrail_matches_accented_company_name_in_truth_and_draft():
    """An accented company in the truth matches the same name in a draft."""
    from guardrail.validate import Scope, validate

    truth_scope = Scope(id="job", texts=[], allowed=["Škoda Auto — Brno"])
    result = validate([truth_scope])
    assert result.ok


def test_legacy_answers_yaml_migrates_to_neutral_field(data_dir):
    """An answers.yaml written by an older build loses no stored answer."""
    from truth.answers import load, save

    raw = {"authorized_non_german_country": "Yes, EU blue card"}
    (data_dir / "answers.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    a = load()
    assert a.work_authorisation_note == "Yes, EU blue card"
    assert a.authorized_non_german_country == "Yes, EU blue card"
    # A round-trip save preserves both keys.
    save(a)
    b = load()
    assert b.work_authorisation_note == "Yes, EU blue card"
    assert b.authorized_non_german_country == "Yes, EU blue card"


def test_neutral_work_authorisation_note_wins_when_set():
    """Once the neutral field carries its own value it is never overwritten."""
    from truth.answers import Answers

    a = Answers.from_dict(
        {"authorized_non_german_country": "old", "work_authorisation_note": "new"}
    )
    assert a.work_authorisation_note == "new"


def test_seed_canonical_cv_without_asset_raises_clear_error(data_dir):
    """No argument + no bundled asset: an error naming what to supply."""
    from truth.answers import seed_canonical_cv

    try:
        seed_canonical_cv()
        raised = None
    except FileNotFoundError as exc:
        raised = exc
    assert raised is not None
    assert "canonical_cv.pdf" in str(raised)
    assert "python -m truth.answers" in str(raised)


def test_unicode_names_tokenize_as_single_tokens():
    """Accented names/companies tokenize as one token, not shattered ASCII."""
    from guardrail.validate import _tokenize

    assert _tokenize("Klaus Müller") == ["klaus", "müller"]
    assert _tokenize("Škoda Auto") == ["škoda", "auto"]


def test_guardrail_matches_accented_company_name_in_truth_and_draft():
    """An accented company in the truth matches the same name in a draft."""
    from guardrail.validate import Scope, validate

    result = validate(
        [Scope(id="job", texts=["Škoda Auto"], allowed=["Škoda Auto", "senior", "engineer"])]
    )
    assert result.ok, result.unverifiable


def test_operator_supplied_stopwords_stop_being_flagged(data_dir):
    """Words listed on the data volume are no longer unverifiable claims."""
    # guardrail/__init__ re-exports the validate() function over the
    # submodule name, so reach the module through sys.modules.
    import sys

    gv = sys.modules["guardrail.validate"]
    from guardrail.validate import Scope, validate

    # Without a file, a non-stopword word is flagged (existing behaviour).
    result = validate([Scope(id="j", texts=["Zwischen"], allowed=[])])
    assert "zwischen" in result.unverifiable

    vocab = data_dir / "stopwords.txt"
    vocab.write_text("# extra connectives\nzwischen\nund\n", encoding="utf-8")
    gv._stopwords_cache = None  # reset the per-data_dir cache for this test

    result = validate([Scope(id="j", texts=["Zwischen"], allowed=[])])
    assert result.unverifiable == []

    gv._stopwords_cache = None


def test_empty_provider_falls_back_to_verbatim_truth(data_dir):
    provider = FakeProvider()  # returns schema-empty
    truth = _truth()
    result = tailor("posting", truth, lambda task=None: provider)
    # fallback carries truth experiences verbatim, still only real ids
    assert {e.source_id for e in result["draft"].experiences} == {
        e.id for e in truth.experiences
    }
    assert result["draft"].skills == [s.value for s in truth.skills]
