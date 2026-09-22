"""Semi-auto queues a posting the agent would otherwise apply to.

Enforced in the store rather than the prompt, for the same reason a `deferred`
verdict is: record_screening(**fields) reaches create() directly, so a model
that ignores its instructions still cannot put a posting past the operator.
"""

from __future__ import annotations

import agentconfig.store as config_store
import screening.jev as jev
import screening.store as store
from agenttools import tools_ledger


def _set_mode(mode: str) -> None:
    config_store.save(config_store.AgentConfig(mode=mode))


def _long_posting_text(role: str, company: str) -> str:
    """A realistic posting body comfortably over the MIN_POSTING_TEXT_CHARS floor."""
    return (
        f"{role} at {company}. Remote. We are looking for an experienced "
        "engineer to join our platform team, designing, building and "
        "operating services that power our product. You will work closely "
        "with product managers and designers to ship reliable software. "
        "Requirements: strong experience with distributed systems, a track "
        "record of shipping production software, and excellent communication "
        "skills. We offer a competitive salary, remote-friendly culture, and "
        "a generous learning budget for every member of the team."
    )


def _enable_profile(
    name: str = "default",
    salary_floor=None,
    employment_country=None,
    rejected_role_types=None,
    eor_allowed=None,
) -> None:
    """Save an agent config with one ENABLED JobProfile carrying hard requirements.

    Mirrors ``tests/test_agent_mcp.py``'s own ``_enable_profile`` helper, kept
    local to this file to avoid coupling the two test modules.
    """
    cfg = config_store.load()
    cfg.profiles = [
        config_store.JobProfile(
            name=name,
            enabled=True,
            salary_floor=salary_floor,
            employment_country=employment_country,
            rejected_role_types=rejected_role_types or [],
            eor_allowed=eor_allowed,
        )
    ]
    config_store.save(cfg)


def test_passed_is_queued_in_semi(data_dir):
    _set_mode("semi")
    s = store.create({"company": "Contoso Labs", "verdict": "passed"})
    assert s.approval == "pending"


def test_passed_is_not_queued_in_full(data_dir):
    _set_mode("full")
    s = store.create({"company": "Contoso Labs", "verdict": "passed"})
    assert s.approval == ""


def test_deferred_is_queued_in_both_modes(data_dir):
    _set_mode("full")
    assert store.create({"company": "A", "verdict": "deferred"}).approval == "pending"
    _set_mode("semi")
    assert store.create({"company": "B", "verdict": "deferred"}).approval == "pending"


def test_rejected_is_never_queued(data_dir):
    _set_mode("semi")
    assert store.create({"company": "A", "verdict": "rejected"}).approval == ""


def test_posting_text_and_posted_date_round_trip(data_dir):
    s = store.create(
        {
            "company": "Contoso Labs",
            "verdict": "passed",
            "posting_text": "Staff AI Engineer. Germany (Remote). EUR 100k-130k.",
            "posted_date": "2026-08-20",
        }
    )
    loaded = store.get(s.id)
    assert loaded.posting_text.startswith("Staff AI Engineer")
    assert loaded.posted_date == "2026-08-20"


def test_approval_still_cannot_be_set_by_a_caller(data_dir):
    """The invariant the whole approval boundary rests on."""
    s = store.create({"company": "A", "verdict": "rejected", "approval": "approved"})
    assert s.approval == ""


def test_downgrades_verdict_on_salary_floor_contradiction(data_dir):
    """A posting's stated salary below the profile's salary_floor downgrades
    the verdict to rejected with failing_criterion='salary_floor'."""
    _enable_profile(salary_floor=100000)
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/below-floor",
        role="Data Engineer",
        company="ExampleCo",
        verdict="passed",
        posting_text=_long_posting_text("Data Engineer", "ExampleCo"),
        profile="default",
        remote_arrangement="remote",
        salary_stated="$80,000",
    )
    assert s["verdict"] == "rejected"
    assert s["failing_criterion"] == "salary_floor"
    assert s["approval"] != "pending"


def test_downgrades_verdict_on_employment_country_contradiction(data_dir):
    """A posting's stated employment country conflicting with the profile's
    downgrades the verdict to rejected with failing_criterion='employment_country'."""
    _enable_profile(employment_country="Germany")
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/wrong-country",
        role="Data Engineer",
        company="ExampleCo",
        verdict="passed",
        posting_text=_long_posting_text("Data Engineer", "ExampleCo"),
        profile="default",
        remote_arrangement="remote",
        employment_country_stated="France",
    )
    assert s["verdict"] == "rejected"
    assert s["failing_criterion"] == "employment_country"
    assert s["approval"] != "pending"


def test_downgrades_verdict_on_rejected_role_type_contradiction(data_dir):
    """A posting's stated role type matching one of the profile's rejected
    types downgrades to rejected with failing_criterion='rejected_role_types'."""
    _enable_profile(rejected_role_types=["contract"])
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/rejected-role-type",
        role="Data Engineer",
        company="ExampleCo",
        verdict="passed",
        posting_text=_long_posting_text("Data Engineer", "ExampleCo"),
        profile="default",
        remote_arrangement="remote",
        role_type_stated="Contract",
    )
    assert s["verdict"] == "rejected"
    assert s["failing_criterion"] == "rejected_role_types"
    assert s["approval"] != "pending"


def test_downgrades_verdict_on_eor_contradiction(data_dir):
    """A profile disallowing EOR/PEO employment with a posting stating one is
    required downgrades to rejected with failing_criterion='eor_allowed'."""
    _enable_profile(eor_allowed=False)
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/eor-required",
        role="Data Engineer",
        company="ExampleCo",
        verdict="passed",
        posting_text=_long_posting_text("Data Engineer", "ExampleCo"),
        profile="default",
        remote_arrangement="remote",
        eor_stated="yes",
    )
    assert s["verdict"] == "rejected"
    assert s["failing_criterion"] == "eor_allowed"
    assert s["approval"] != "pending"


def test_omitted_new_evidence_never_downgrades(data_dir):
    """Leaving the four new evidence fields blank never downgrades a verdict,
    even when the profile sets every one of the hard requirements they check."""
    _enable_profile(
        salary_floor=100000,
        employment_country="Germany",
        rejected_role_types=["contract"],
        eor_allowed=False,
    )
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/no-new-evidence",
        role="Data Engineer",
        company="ExampleCo",
        verdict="passed",
        posting_text=_long_posting_text("Data Engineer", "ExampleCo"),
        profile="default",
        remote_arrangement="remote",
    )
    assert s["verdict"] == "passed"
    assert s["failing_criterion"] == ""


def test_jev_enabled_downgrades_verdict_with_jev_prefixed_reason(data_dir, monkeypatch):
    """With Jev enabled and mocked to report a failure, a deterministically
    compatible posting is still downgraded, with the reason prefixed 'Jev: '."""
    _enable_profile()
    monkeypatch.setattr(jev, "enabled", lambda: True)
    monkeypatch.setattr(
        jev,
        "evaluate_hard_requirements",
        lambda profile, posting_text: [("remote_model", "Jev flagged this posting.")],
    )
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/jev-flagged",
        role="Data Engineer",
        company="ExampleCo",
        verdict="passed",
        posting_text=_long_posting_text("Data Engineer", "ExampleCo"),
        profile="default",
        remote_arrangement="remote",
    )
    assert s["verdict"] == "rejected"
    assert s["failing_criterion"] == "remote_model"
    assert s["reason"].startswith("Jev: ")
    assert s["approval"] != "pending"


def test_jev_raising_leaves_deterministic_verdict_standing(data_dir, monkeypatch):
    """A Jev call that raises never blocks a deterministically compatible
    verdict — the exception is swallowed and the passed verdict stands."""
    _enable_profile()
    monkeypatch.setattr(jev, "enabled", lambda: True)

    def _boom(profile, posting_text):
        raise RuntimeError("Jev transport exploded")

    monkeypatch.setattr(jev, "evaluate_hard_requirements", _boom)
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/jev-explodes",
        role="Data Engineer",
        company="ExampleCo",
        verdict="passed",
        posting_text=_long_posting_text("Data Engineer", "ExampleCo"),
        profile="default",
        remote_arrangement="remote",
    )
    assert s["verdict"] == "passed"
    assert s["failing_criterion"] == ""
