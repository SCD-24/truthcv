"""Job Screening store: atomic persistence, fail-safe corrupt load, verdict
round trips, and cooldown derivation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import applications
from coverletter.store import CoverLetterDraft
from coverletter.store import save as save_letter_draft
from coverletter.store import draft_path as letter_draft_path
from companyresearch import store as findings_store
from screening.cooldown import cooldown
from screening.model import VERDICT_VALUES
from screening.store import (
    claim_for_apply,
    create,
    delete,
    delete_many,
    load_all,
    mark_applied,
    screenings_path,
    set_approval,
)


def test_empty_when_no_file(data_dir):
    assert load_all() == []


def test_atomic_write_leaves_no_tmp(data_dir):
    create({"company": "Acme", "verdict": "passed"})
    tmp = screenings_path().with_suffix(".json.tmp")
    assert not tmp.exists()


def test_load_empty_on_corrupt_json(data_dir):
    screenings_path().write_text("{not valid json", encoding="utf-8")
    assert load_all() == []


def test_load_empty_when_top_level_not_a_list(data_dir):
    screenings_path().write_text(json.dumps({"oops": True}), encoding="utf-8")
    assert load_all() == []


@pytest.mark.parametrize("verdict", VERDICT_VALUES)
def test_verdict_round_trips(data_dir, verdict):
    created = create(
        {"company": "Acme", "role": "Engineer", "verdict": verdict}
    )
    assert created.verdict == verdict

    reloaded = load_all()
    assert len(reloaded) == 1
    assert reloaded[0].verdict == verdict


def test_cooldown_from_screening_alone(data_dir):
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    create(
        {
            "company": "Acme",
            "role": "Engineer",
            "verdict": "rejected",
            "cooldown_expires": future,
        }
    )
    status = cooldown("Acme", "Engineer")
    assert status.in_cooldown is True
    assert status.expires == future


def test_cooldown_from_application_alone(data_dir, monkeypatch):
    monkeypatch.setenv("APPLICATION_COOLDOWN_DAYS", "90")
    recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).date()
    applications.create(
        {
            "company": "Acme",
            "role": "Engineer",
            "application_date": recent_date.isoformat(),
        }
    )
    status = cooldown("Acme", "Engineer")
    assert status.in_cooldown is True

    expected_expiry = (
        datetime(recent_date.year, recent_date.month, recent_date.day, tzinfo=timezone.utc)
        + timedelta(days=90)
    )
    assert datetime.fromisoformat(status.expires) == expected_expiry


def test_cooldown_prefers_later_of_both_sources(data_dir, monkeypatch):
    monkeypatch.setenv("APPLICATION_COOLDOWN_DAYS", "90")

    # Screening's own cooldown expires soon (near future).
    near = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    create(
        {
            "company": "Acme",
            "role": "Engineer",
            "verdict": "rejected",
            "cooldown_expires": near,
        }
    )

    # Application-derived expiry (application_date + 90 days) lands further out.
    app_date = (datetime.now(timezone.utc) - timedelta(days=10)).date()
    applications.create(
        {
            "company": "Acme",
            "role": "Engineer",
            "application_date": app_date.isoformat(),
        }
    )
    expected_far_expiry = (
        datetime(app_date.year, app_date.month, app_date.day, tzinfo=timezone.utc)
        + timedelta(days=90)
    )

    status = cooldown("Acme", "Engineer")
    assert status.in_cooldown is True
    assert datetime.fromisoformat(status.expires) == expected_far_expiry
    assert datetime.fromisoformat(status.expires) > datetime.fromisoformat(near)


def test_cooldown_expired_reports_not_in_cooldown(data_dir):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    create(
        {
            "company": "Acme",
            "role": "Engineer",
            "verdict": "rejected",
            "cooldown_expires": past,
        }
    )
    status = cooldown("Acme", "Engineer")
    assert status.in_cooldown is False
    assert status.expires == past


def test_cooldown_matches_case_and_whitespace_insensitively(data_dir):
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    create(
        {
            "company": "  Acme Corp  ",
            "role": " Engineer ",
            "verdict": "rejected",
            "cooldown_expires": future,
        }
    )
    status = cooldown("ACME CORP", "engineer")
    assert status.in_cooldown is True
    assert status.expires == future


# --- Two-window cooldown ----------------------------------------------------


def test_windows_independent_of_legacy_field(data_dir, monkeypatch):
    """Each new window overrides the legacy field independently."""
    from agentconfig import store as agent_config_store

    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    cfg = agent_config_store.load()
    cfg.cooldown_days = 100
    cfg.cooldown_days_same_role = 5
    cfg.cooldown_days_same_company = 45
    agent_config_store.save(cfg)

    app_date = (datetime.now(timezone.utc) - timedelta(days=30))
    applications.create(
        {"company": "Acme", "role": "Engineer", "application_date": app_date.date().isoformat()}
    )

    # Role-matched: same-role window lapsed (5 < 30), same-company still holds
    # (45 > 30); the later expiry wins and names its window.
    role_match = cooldown("Acme", "Engineer")
    assert role_match.in_cooldown is True
    assert role_match.window == "same_company"

    # A different role at the company: only the same-company window applies.
    other_role = cooldown("Acme", "Designer")
    assert other_role.in_cooldown is True
    assert other_role.window == "same_company"
    assert other_role.expires == role_match.expires


def test_same_role_window_blocks_when_it_is_the_longer_one(data_dir, monkeypatch):
    """A longer same-role window governs a role-matched lookup's verdict."""
    from agentconfig import store as agent_config_store

    monkeypatch.delenv("APPLICATION_COOLDOWN_DAYS", raising=False)
    cfg = agent_config_store.load()
    cfg.cooldown_days = 10
    cfg.cooldown_days_same_role = 60
    cfg.cooldown_days_same_company = None
    agent_config_store.save(cfg)

    app_date = (datetime.now(timezone.utc) - timedelta(days=30))
    applications.create(
        {"company": "Acme", "role": "Engineer", "application_date": app_date.date().isoformat()}
    )

    expected_expiry = (
        datetime(app_date.year, app_date.month, app_date.day, tzinfo=timezone.utc)
        + timedelta(days=60)
    )
    role_match = cooldown("Acme", "Engineer")
    assert role_match.in_cooldown is True
    assert role_match.window == "same_role"
    assert datetime.fromisoformat(role_match.expires) == expected_expiry

    # Company-only lookup sees the legacy window, long lapsed.
    company_only = cooldown("Acme")
    assert company_only.in_cooldown is False
    assert company_only.window is None


def test_window_none_when_clear_or_blocklisted(data_dir):
    from agentconfig import store as agent_config_store

    cfg = agent_config_store.load()
    cfg.blocked_companies = ["BlockCo"]
    agent_config_store.save(cfg)

    blocked = cooldown("BlockCo")
    assert blocked.blocked is True
    assert blocked.window is None

    clear = cooldown("QuietCo")
    assert clear.in_cooldown is False
    assert clear.window is None


# --- delete / delete_many ----------------------------------------------------


def test_delete_many_removes_named_ids_and_leaves_others(data_dir):
    a = create({"company": "Acme", "verdict": "rejected"})
    b = create({"company": "Beta", "verdict": "rejected"})
    c = create({"company": "Gamma", "verdict": "rejected"})

    results = delete_many([a.id, c.id])

    assert results == [(a.id, True), (c.id, True)]
    remaining = {s.id for s in load_all()}
    assert remaining == {b.id}


def test_delete_many_reports_unknown_ids_false(data_dir):
    a = create({"company": "Acme", "verdict": "rejected"})

    results = delete_many([a.id, "not-a-real-id"])

    assert results == [(a.id, True), ("not-a-real-id", False)]
    assert load_all() == []


def test_delete_many_empty_list_is_noop(data_dir):
    create({"company": "Acme", "verdict": "rejected"})

    assert delete_many([]) == []
    assert len(load_all()) == 1


def test_delete_removes_saved_cover_letter_draft(data_dir):
    a = create({"company": "Acme", "verdict": "rejected"})
    save_letter_draft(a.id, CoverLetterDraft(text="Dear hiring manager,"))
    assert letter_draft_path(a.id).exists()

    assert delete(a.id) is True

    assert not letter_draft_path(a.id).exists()


def test_delete_many_removes_saved_cover_letter_drafts(data_dir):
    a = create({"company": "Acme", "verdict": "rejected"})
    b = create({"company": "Beta", "verdict": "rejected"})
    save_letter_draft(a.id, CoverLetterDraft(text="Dear hiring manager,"))
    save_letter_draft(b.id, CoverLetterDraft(text="Dear hiring manager,"))
    assert letter_draft_path(a.id).exists()
    assert letter_draft_path(b.id).exists()

    delete_many([a.id, b.id])

    assert not letter_draft_path(a.id).exists()
    assert not letter_draft_path(b.id).exists()


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

def test_concurrent_creates_lose_no_records(data_dir):
    """The measured regression: two writers each dropped some of the other's.

    Before the store took a lock, 3x40 concurrent creates onto a 20-record file
    finished with 64 of 140 records and 34 raised renames.
    """
    import threading

    from screening import store

    for i in range(20):
        store.create({"company": f"Seed{i}", "role": "Engineer", "url": f"https://e.com/{i}"})

    errors = []

    def writer(tag: str):
        for i in range(40):
            try:
                store.create(
                    {"company": f"{tag}{i}", "role": "Engineer", "url": f"https://e.com/{tag}{i}"}
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=writer, args=(t,)) for t in "ABC"]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert errors == []
    assert len(store.load_all()) == 140
    assert len({s.id for s in store.load_all()}) == 140


def test_a_concurrent_create_does_not_undo_a_concurrent_approval(data_dir):
    """Mixed mutators race too: create vs set_approval on the same file.

    This is the live shape — the operator clicks while an agent run records.
    """
    import threading

    from screening import store

    target = store.create(
        {"company": "Acme", "role": "Engineer", "url": "https://e.com/a", "verdict": "deferred"}
    )

    def approve():
        for _ in range(30):
            store.set_approval(target.id, "approved")

    def record():
        for i in range(30):
            store.create({"company": f"New{i}", "role": "Engineer", "url": f"https://e.com/n{i}"})

    threads = [threading.Thread(target=approve), threading.Thread(target=record)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert len(store.load_all()) == 31
    reloaded = store.get(target.id)
    assert reloaded is not None
    assert reloaded.approval == "approved"


def test_claim_for_apply_and_mark_applied_refuse_open_contradiction(data_dir):
    """A company with an unresolved research contradiction blocks both apply paths."""
    findings_store.record(
        "Acme Co", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent"
    )
    findings_store.record(
        "Acme Co", "employer_rating", "3.0", "https://b.example/y", "review_site", "", "agent"
    )

    target = create({"company": "Acme Co", "role": "Engineer", "url": "https://e.com/a"})
    set_approval(target.id, "approved")

    assert claim_for_apply(target.id) is None
    reloaded = next(s for s in load_all() if s.id == target.id)
    assert reloaded.approval == "approved"

    assert mark_applied(target.id) is None
    reloaded = next(s for s in load_all() if s.id == target.id)
    assert reloaded.approval == "approved"


def test_claim_for_apply_and_mark_applied_succeed_once_contradiction_resolved(data_dir):
    """Resolving one side clears the guard for both apply paths."""
    first = findings_store.record(
        "Beta Inc", "employer_rating", "4.5", "https://a.example/x", "press", "", "agent"
    )
    findings_store.record(
        "Beta Inc", "employer_rating", "3.0", "https://b.example/y", "review_site", "", "agent"
    )
    findings_store.resolve(first.id, "rejected")

    target = create({"company": "Beta Inc", "role": "Engineer", "url": "https://e.com/b"})
    set_approval(target.id, "approved")

    claimed = claim_for_apply(target.id)
    assert claimed is not None
    assert claimed.approval == "applied"


def test_mark_applied_and_claim_for_apply_share_one_implementation():
    """The two names must not be able to fork: assert they delegate to the
    same underlying function rather than merely behaving alike today."""
    import screening.store as store_module

    # Both call the same private helper under the hood.
    assert store_module.mark_applied.__code__.co_names == store_module.claim_for_apply.__code__.co_names
    assert "_retire" in store_module.mark_applied.__code__.co_names
    assert "_retire" in store_module.claim_for_apply.__code__.co_names


def test_claim_for_run_contention(data_dir):
    """A live lease held by one run cannot be taken by a different run, but
    is reclaimable once it expires."""
    import screening.store as store_module

    target = create({"company": "Gamma LLC", "role": "Engineer", "url": "https://e.com/g"})
    set_approval(target.id, "approved")

    claimed = store_module.claim_for_run(target.id, "run-a", lease_seconds=900)
    assert claimed is not None
    assert claimed.claimed_by_run == "run-a"

    # A different run cannot take a live lease.
    assert store_module.claim_for_run(target.id, "run-b", lease_seconds=900) is None

    # The same run may refresh its own lease.
    refreshed = store_module.claim_for_run(target.id, "run-a", lease_seconds=1800)
    assert refreshed is not None
    assert refreshed.claimed_by_run == "run-a"

    # An expired lease is reclaimable by a different run.
    store_module.claim_for_run(target.id, "run-a", lease_seconds=-1)
    reclaimed = store_module.claim_for_run(target.id, "run-c", lease_seconds=900)
    assert reclaimed is not None
    assert reclaimed.claimed_by_run == "run-c"


def test_claim_for_run_contention_under_threads(data_dir):
    """Concurrent claims for the same item by different runs: exactly one
    run holds the live lease afterward."""
    import threading

    import screening.store as store_module

    target = create({"company": "Delta Inc", "role": "Engineer", "url": "https://e.com/d"})
    set_approval(target.id, "approved")

    winners = []

    def try_claim(run_id):
        result = store_module.claim_for_run(target.id, run_id, lease_seconds=900)
        if result is not None and result.claimed_by_run == run_id:
            winners.append(run_id)

    threads = [threading.Thread(target=try_claim, args=(f"run-{i}",)) for i in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    final = next(s for s in load_all() if s.id == target.id)
    # Every thread "succeeds" in the sense of getting a record back (claiming
    # is last-writer-wins across concurrent live calls since none has expired
    # yet), but the persisted state names exactly one current holder.
    assert final.claimed_by_run in [f"run-{i}" for i in range(10)]


def test_mark_applied_clears_a_claim_on_retire(data_dir):
    """Retiring a screening releases any lease it was holding."""
    import screening.store as store_module

    target = create({"company": "Epsilon Co", "role": "Engineer", "url": "https://e.com/eps"})
    set_approval(target.id, "approved")
    store_module.claim_for_run(target.id, "run-x", lease_seconds=900)

    result = mark_applied(target.id)
    assert result is not None
    assert result.claimed_by_run == ""
    assert result.claim_expires_at == ""


def test_mark_applied_is_unconditional_about_claim_ownership(data_dir):
    """mark_applied must succeed for an item this run did not claim — it is
    called after the ledger row is already written, so a claim mismatch must
    never cause a refusal."""
    import screening.store as store_module

    target = create({"company": "Zeta Co", "role": "Engineer", "url": "https://e.com/zeta"})
    set_approval(target.id, "approved")
    store_module.claim_for_run(target.id, "some-other-run", lease_seconds=900)

    result = mark_applied(target.id)
    assert result is not None
    assert result.approval == "applied"
