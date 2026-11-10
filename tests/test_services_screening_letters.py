"""Error branches of services.screening_letters and the screening services
extracted from api/routes.py: each raises the ServiceError the route's HTTP
status maps to, with the route's exact detail text/payload."""

from __future__ import annotations

import pytest

import truthcv.engines.coverletter.store as letter_store
import truthcv.services.letters as letters
import truthcv.services.screening_letters as sl
import truthcv.services.screenings as svc
from truthcv.domain.screening import store
from truthcv.services.errors import Conflict, NotFound, Refused

URL = "https://acme.example/jobs/1"


def _screening(posting_text="We need an engineer.", **extra):
    fields = {"company": "Acme", "role": "Engineer", "url": URL, "verdict": "passed"}
    s, _ = store.create_or_get({**fields, "posting_text": posting_text, **extra})
    return s


def _gen(sid, **kw):
    args = dict(force=False, approved_ids=None, denied_ids=None, paragraphs=None,
                preset_id=None, length="medium", provider_factory=None)
    return sl.generate(sid, **{**args, **kw})


def _conflict_text(exc):
    assert exc.value.payload == str(exc.value)
    return str(exc.value)


# --- generate --------------------------------------------------------------

def test_generate_unknown_screening_is_not_found():
    with pytest.raises(NotFound, match="^Screening not found.$"):
        _gen("nope")


def test_generate_without_posting_text_conflicts():
    s = _screening(posting_text="")
    with pytest.raises(Conflict) as exc:
        _gen(s.id)
    assert _conflict_text(exc) == (
        "No posting text stored for this screening, so there is nothing to draft from."
    )


def test_generate_refuses_to_overwrite_operator_edit_unless_forced(monkeypatch):
    s = _screening()
    letter_store.save(s.id, letter_store.CoverLetterDraft(text="mine", paragraphs=[], source="operator"))
    with pytest.raises(Conflict) as exc:
        _gen(s.id)
    assert _conflict_text(exc) == (
        "This letter was edited by you. Redrafting would discard those edits."
    )
    monkeypatch.setattr(letters, "generate_cover_letter_for_operator",
                        lambda **kw: {"blocked": False, "text": "new", "paragraphs": []})
    assert _gen(s.id, force=True).source == "generated"


def test_generate_blocked_raises_structured_refusal(monkeypatch):
    s = _screening()
    seen = {}
    para = [{"text": "p", "claims": ["Led X"]}]

    def fake(**kw):
        seen.update(kw)
        return {"blocked": True, "blocked_reason": "unverified",
                "blocked_claims": [{"scope_id": "letter", "text": "Led X", "tokens": ["X"]}],
                "paragraphs": para}

    monkeypatch.setattr(letters, "generate_cover_letter_for_operator", fake)
    from truthcv.engines.coverletter import LETTER_SCOPE_ID
    from truthcv.services.render_cv import _claim_id
    cid = _claim_id(LETTER_SCOPE_ID, "Led X")
    with pytest.raises(Refused) as exc:
        _gen(s.id, approved_ids={cid}, denied_ids=set(), paragraphs=para)
    assert seen["approved_texts"] == {"Led X"} and seen["denied_texts"] == set()
    assert exc.value.payload == {
        "message": "The letter was blocked by the truthfulness guardrail.",
        "blockedReason": "unverified",
        "blockedClaims": [{"claimId": _claim_id("letter", "Led X"), "experienceId": "letter",
                           "text": "Led X", "tokens": ["X"]}],
        "paragraphs": para,
    }
    assert letter_store.load(s.id) is None


# --- save_operator_text ----------------------------------------------------

def test_save_operator_text_errors_and_keeps_paragraphs():
    with pytest.raises(NotFound, match="^Screening not found.$"):
        sl.save_operator_text("nope", "hi")
    s = _screening()
    with pytest.raises(Refused) as exc:
        sl.save_operator_text(s.id, "   ")
    assert exc.value.payload == (
        "An empty letter cannot be saved — blanking is not an edit; regenerate instead."
    )
    letter_store.save(s.id, letter_store.CoverLetterDraft(text="g", paragraphs=[{"text": "g"}], source="generated"))
    draft = sl.save_operator_text(s.id, "mine")
    assert (draft.text, draft.paragraphs, draft.source) == ("mine", [{"text": "g"}], "operator")


# --- services.screenings ---------------------------------------------------

def test_bulk_set_approval_swallows_conflict_and_refuses_bad_value():
    a = _screening(profile="A", verdict="rejected")
    b = _screening(profile="B", verdict="rejected")
    store.set_approval(a.id, "approved")
    assert svc.bulk_set_approval([b.id, "nope"], "approved") == [
        {"id": b.id, "ok": False}, {"id": "nope", "ok": False}]
    with pytest.raises(Refused) as exc:
        svc.bulk_set_approval([a.id], "bogus")
    assert exc.value.payload == "Unknown approval state 'bogus'."


def test_mark_applied_errors_and_creates_application():
    with pytest.raises(NotFound, match="^Screening not found.$"):
        svc.mark_applied("nope")
    s = _screening()
    app = svc.mark_applied(s.id)
    assert (app.company, app.capture_method, app.screening_id) == ("Acme", "manual", s.id)
    with pytest.raises(Conflict) as exc:
        svc.mark_applied(s.id)
    assert _conflict_text(exc) == "This screening has already been applied to."


def test_update_screening_errors():
    with pytest.raises(NotFound, match="^Screening not found.$"):
        svc.update_screening("nope", url=URL)
    with pytest.raises(NotFound, match="^Screening not found.$"):
        svc.update_screening("nope", approval="approved")
    a = _screening(profile="A", verdict="rejected")
    b = _screening(profile="B", verdict="rejected")
    with pytest.raises(Refused, match="^Unknown approval state 'bogus'.$"):
        svc.update_screening(a.id, approval="bogus")
    store.set_approval(a.id, "approved")
    with pytest.raises(Conflict) as exc:
        svc.update_screening(b.id, role="Lead", approval="approved")
    assert _conflict_text(exc) == f"Screening {a.id} already holds the approval for this posting."
    assert store.get(b.id).role == "Lead"


def test_rejected_page_clamps_bounds():
    page = svc.rejected_page(10**6, -5, store.REJECTED_ALL)
    assert (page.limit, page.offset, page.total) == (store.REJECTED_PAGE_MAX_LIMIT, 0, 0)


def test_signin_queue_groups_by_host():
    s = _screening()
    store.set_approval(s.id, "pending")
    store.record_apply_failure(s.id, "wall", blocker="login_required",
                               signin_url="https://Login.Acme.example/in")
    sites = svc.signin_queue()
    assert [(e["host"], e["waiting"], e["companies"]) for e in sites] == [
        ("login.acme.example", 1, ["Acme"])]
    assert svc.host_of("not a url") == ""
