"""Guard tests for the agent tool surface (mcp/): the approve/deny gate is the
product, and a human — never the unattended agent — approves an unverifiable
claim. These tests pin down that no registered tool, on either the in-process
registry or the HTTP `/mcp/tools` surface the agent actually sees, exposes any
parameter that could let an agent self-approve an inference, and that no tool
module can reach into the guardrail's allow list to widen what is permitted.

Task t-4 appends end-to-end tests to this same file later; keep additions here
scoped to the guard itself.
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from api.main import app
from applications.store import load_all as load_applications
from agenttools import server as mcp_server
from agenttools import tools_ledger, tools_letter, tools_boards, tools_research
from companyresearch import store as company_findings_store
from providers.fake import FakeProvider
from truth.answers import register_canonical_cv
from truth.model import Bullet, Experience, Skill, Truth
from truth.store import save as save_truth

# Vocabulary a tool parameter must never match: anything that could let the
# agent itself mark an unverifiable claim as approved/confirmed/accepted.
_APPROVAL_VOCAB = re.compile(r"approv|confirm_inference|accept_unverifiable", re.IGNORECASE)


def _approval_params(fn: Callable[..., dict]) -> list[str]:
    """The parameter names of `fn` that match approval vocabulary, if any.

    Factored out so the "no tool takes an approval parameter" check used to
    assert the guard holds (test 1) is exactly the same check used to prove
    the guard has teeth (test 4) — the two can never drift apart.
    """
    params = inspect.signature(fn).parameters
    return [name for name in params if _APPROVAL_VOCAB.search(name)]


def test_no_registered_tool_accepts_an_approval_parameter():
    """No tool in the in-process registry (mcp.server.TOOLS) may accept a
    parameter that could let the unattended agent approve its own inference.
    Approval is a human act; if a tool grew such a parameter, this must fail
    and name the offending tool and parameter."""
    # Guard the guard: an empty registry would let every check below pass
    # vacuously, so pin down that the surface is actually populated.
    assert set(mcp_server.TOOLS) == {
        "generate_cover_letter",
        "record_application",
        "record_screening",
        "check_cooldown",
        "get_canonical_cv",
        "get_profile_answers",
        "record_company_board",
        "get_job_profiles",
        "recommend_salary",
        "record_company_finding",
        "get_company_findings",
    }
    offenses = []
    for name, fn in mcp_server.TOOLS.items():
        for param in _approval_params(fn):
            offenses.append(f"{name}.{param}")
    assert not offenses, f"tool(s) with an approval-shaped parameter: {offenses}"


def test_the_tool_listing_route_exposes_no_approval_parameter():
    """GET /mcp/tools is the surface the agent actually sees at runtime, so it
    must be checked independently of the in-process registry: a mismatch
    between the two would let an approval parameter slip through undetected."""
    client = TestClient(app)
    r = client.get("/mcp/tools")
    assert r.status_code == 200
    offenses = []
    for tool in r.json()["tools"]:
        for param in tool["params"]:
            if _APPROVAL_VOCAB.search(param):
                offenses.append(f"{tool['name']}.{param}")
    assert not offenses, f"tool(s) with an approval-shaped parameter: {offenses}"


def test_no_tool_module_reaches_the_guardrail_allow_list():
    """No tool module may widen what the guardrail permits: none may fold
    into `approved_texts`, import `guardrail`, or call `validate(`/`Scope(`
    directly. Only a human-driven route (api/routes.py) may do that. The
    module list is discovered from the registered tools' `__module__`, so a
    tool added in a new module is covered automatically."""
    module_names = {fn.__module__ for fn in mcp_server.TOOLS.values()}
    modules = {
        tools_letter.__name__: tools_letter,
        tools_ledger.__name__: tools_ledger,
        tools_boards.__name__: tools_boards,
        tools_research.__name__: tools_research,
    }
    assert module_names <= modules.keys(), (
        f"unknown tool module(s), extend this test's module map: {module_names - modules.keys()}"
    )
    for module_name in module_names:
        source = inspect.getsource(modules[module_name])
        assert "approved_texts" not in source, f"{module_name} references approved_texts"
        assert "import guardrail" not in source, f"{module_name} imports guardrail"
        assert "from guardrail" not in source, f"{module_name} imports guardrail"
        assert "validate(" not in source, f"{module_name} calls validate("
        assert "Scope(" not in source, f"{module_name} calls Scope("


def test_the_guard_actually_bites():
    """Prove test 1's check has teeth: registering a throwaway tool with an
    approval parameter must make `_approval_params` flag it. The registry is
    restored to its original contents in a finally block, and that restoration
    is itself asserted."""
    original = dict(mcp_server.TOOLS)

    def approve_inference(claim: str, approved: bool) -> dict:
        return {"claim": claim, "approved": approved}

    try:
        mcp_server.register("approve_inference", approve_inference)
        offenses = []
        for name, fn in mcp_server.TOOLS.items():
            for param in _approval_params(fn):
                offenses.append(f"{name}.{param}")
        assert offenses == ["approve_inference.approved"]
    finally:
        mcp_server.TOOLS.clear()
        mcp_server.TOOLS.update(original)

    assert mcp_server.TOOLS == original


# --- End-to-end tests for the tool surface (task t-4) --------------------------
#
# These exercise the tools themselves rather than the guard around them: per-
# application isolation, the deny/retry round trip without a second LLM call,
# the full evidence trail persisting through record_application, and the
# check_cooldown tool agreeing with its HTTP twin.


def _seed_truth() -> None:
    """Persist a minimal truth to the current DATA_DIR so a scripted claim
    that names this experience/skill validates against it."""
    truth = Truth(
        experiences=[
            Experience(
                id="exp-acme-1",
                role="Senior Engineer",
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
    save_truth(truth)


def _paragraph(text: str, claims: list[str] | None = None) -> dict:
    """One scripted letter paragraph, in the shape the provider must return."""
    return {"text": text, "claims": claims or []}


def test_two_applications_do_not_share_letter_state(data_dir):
    """generate_cover_letter takes its posting/provider per call and returns
    its letter rather than caching anything global, so two applications
    generated back to back must never see each other's text — and neither may
    touch the wizard's global posting.txt or cover_letter_draft.json. This is
    the test that would have caught N concurrent applications clobbering each
    other's state."""
    _seed_truth()
    fake_a = FakeProvider(
        json_responses=[
            {"paragraphs": [_paragraph("AAAA marker sentence about Acme Corp.", ["Acme Corp"])]}
        ]
    )
    fake_b = FakeProvider(
        json_responses=[
            {"paragraphs": [_paragraph("BBBB marker sentence about Python.", ["Python"])]}
        ]
    )

    result_a = tools_letter.generate_cover_letter("Posting A", "Professional", "Short", provider=fake_a)
    result_b = tools_letter.generate_cover_letter("Posting B", "Professional", "Short", provider=fake_b)

    assert result_a["blocked"] is False
    assert result_b["blocked"] is False
    assert "AAAA marker" in result_a["text"]
    assert "BBBB marker" not in result_a["text"]
    assert "BBBB marker" in result_b["text"]
    assert "AAAA marker" not in result_b["text"]
    assert not (data_dir / "posting.txt").exists()
    assert not (data_dir / "cover_letter_draft.json").exists()


def test_a_denied_claim_retries_without_a_second_llm_call(data_dir):
    """The deny/retry round trip: a denied claim's paragraph is excised and
    re-validated from the FIRST call's paragraphs, never by asking the
    provider again. The denied claim sits alone in its own paragraph so
    excising it leaves a second, fully-verifiable paragraph behind."""
    _seed_truth()
    fake = FakeProvider(
        json_responses=[
            {
                "paragraphs": [
                    _paragraph("I led Mars colony operations.", ["Led Mars colony operations"]),
                    _paragraph(
                        "As a Senior Engineer at Acme Corp, I build reliable systems.",
                        ["Senior Engineer", "Acme Corp"],
                    ),
                ]
            }
        ]
    )

    first = tools_letter.generate_cover_letter("A role", "Professional", "Short", provider=fake)
    assert first["blocked"] is True
    denied_text = "Led Mars colony operations"
    assert denied_text in [c["text"] for c in first["blocked_claims"]]
    assert len(fake.calls) == 1

    second = tools_letter.generate_cover_letter(
        "A role",
        "Professional",
        "Short",
        denied_texts=[denied_text],
        paragraphs=first["paragraphs"],
        provider=fake,
    )

    # The plan's explicit doneWhen: retrying a denied claim must not cost a
    # second provider call. Making this failure unmissable is the point.
    assert len(fake.calls) == 1, "retry issued a second LLM call; denied_texts+paragraphs must short-circuit generation"
    assert second["blocked"] is False
    assert "Senior Engineer at Acme Corp" in second["text"]
    assert denied_text not in second["text"]


def test_record_application_persists_the_whole_evidence_trail(data_dir):
    """record_application's structured evidence — fields_submitted,
    confirmation, attachments — must survive a reload from disk, not just
    appear in the tool's own return value. confirmation.text especially is
    the only evidence a submission actually happened."""
    created = tools_ledger.record_application(
        company="Acme Corp",
        role="Senior Engineer",
        ats="Greenhouse",
        capture_method="manual",
        applied_date="2026-01-15",
        gaps_disclosed=["No management experience"],
        fields_submitted=[{"label": "Full Name", "value": "Ada Example", "source": "truth"}],
        confirmation={
            "text": "Thank you for applying to Acme Corp.",
            "confirmed_at": "2026-01-15T10:00:00+00:00",
            "evidence": "confirmation_screenshot.png",
        },
        attachments=[{"kind": "cv", "path": "cv_abc123.pdf"}],
    )

    reloaded = next(a for a in load_applications() if a.id == created["id"])
    assert reloaded.company == "Acme Corp"
    assert reloaded.role == "Senior Engineer"
    assert reloaded.ats == "Greenhouse"
    assert reloaded.capture_method == "manual"
    assert reloaded.application_date == "2026-01-15"
    assert reloaded.gaps_disclosed == ["No management experience"]

    assert len(reloaded.fields_submitted) == 1
    field = reloaded.fields_submitted[0]
    assert (field.label, field.value, field.source) == ("Full Name", "Ada Example", "truth")

    assert reloaded.confirmation.text == "Thank you for applying to Acme Corp."
    assert reloaded.confirmation.confirmed_at == "2026-01-15T10:00:00+00:00"
    assert reloaded.confirmation.evidence == "confirmation_screenshot.png"

    assert len(reloaded.attachments) == 1
    attachment = reloaded.attachments[0]
    assert (attachment.kind, attachment.path) == ("cv", "cv_abc123.pdf")


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


def _approve_screening(company: str, role: str, url: str) -> str:
    """Create an approved screening and return its id."""
    s = tools_ledger.record_screening(
        company=company,
        role=role,
        url=url,
        posting_text=_long_posting_text(role, company),
        verdict="deferred",
        source="agent",
    )
    from screening import store as screening_store

    screening_store.set_approval(s["id"], "approved")
    return s["id"]


def test_record_application_backfills_identity_from_the_screening(data_dir):
    """An application recorded against a queue item inherits that item's
    company, role, URL and posting — so the Applications row is populated
    without the agent repeating them — and the screening retires to
    approval='applied' as before."""
    screening_id = _approve_screening(
        "Acme Corp", "Senior Engineer", "https://acme.example/job/1"
    )

    created = tools_ledger.record_application(
        screening_id=screening_id,
        applied_date="2026-02-01",
    )

    reloaded = next(a for a in load_applications() if a.id == created["id"])
    assert reloaded.company == "Acme Corp"
    assert reloaded.role == "Senior Engineer"
    assert reloaded.application_url == "https://acme.example/job/1"
    assert reloaded.posting == _long_posting_text("Senior Engineer", "Acme Corp")

    from screening.store import get as get_screening

    assert get_screening(screening_id).approval == "applied"


def test_record_application_caller_values_beat_the_screening(data_dir):
    """Caller-supplied non-empty identity values always win over the
    screening's — the backfill fills gaps only, never overrides."""
    screening_id = _approve_screening(
        "Acme Corp", "Senior Engineer", "https://acme.example/job/1"
    )

    created = tools_ledger.record_application(
        screening_id=screening_id,
        company="Acme Corporation Ltd",
        application_url="https://acme.example/applied/42",
        applied_date="2026-02-01",
    )

    reloaded = next(a for a in load_applications() if a.id == created["id"])
    assert reloaded.company == "Acme Corporation Ltd"
    assert reloaded.application_url == "https://acme.example/applied/42"
    # Not supplied by the caller, so still inherited.
    assert reloaded.role == "Senior Engineer"


def test_record_application_with_unknown_screening_id_still_creates(data_dir):
    """An unknown screening_id must not raise — the application is created
    from what was passed, exactly as when no screening_id is given."""
    created = tools_ledger.record_application(
        screening_id="no-such-screening",
        company="Solo Co",
        applied_date="2026-02-01",
    )

    reloaded = next(a for a in load_applications() if a.id == created["id"])
    assert reloaded.company == "Solo Co"
    assert not reloaded.application_url


def test_check_cooldown_agrees_with_the_http_route(data_dir):
    """check_cooldown delegates to the same screening.cooldown.cooldown as
    GET /api/cooldown, so the two surfaces must never disagree — proven here
    for both an in-cooldown company and one with no screening at all."""
    client = TestClient(app)
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    tools_ledger.record_screening(
        company="Acme Corp",
        url="https://acme.example/jobs/1",
        role="Senior Engineer",
        verdict="rejected",
        cooldown_expires=future,
    )

    tool_result = tools_ledger.check_cooldown("Acme Corp")
    http_result = client.get("/api/cooldown", params={"company": "Acme Corp"}).json()
    assert tool_result["in_cooldown"] is True
    assert tool_result["in_cooldown"] == http_result["inCooldown"]
    assert tool_result["expires"] == http_result["expires"]

    tool_result_none = tools_ledger.check_cooldown("Nobody Corp")
    http_result_none = client.get("/api/cooldown", params={"company": "Nobody Corp"}).json()
    assert tool_result_none["in_cooldown"] is False
    assert tool_result_none["in_cooldown"] == http_result_none["inCooldown"]
    assert tool_result_none["expires"] == http_result_none["expires"] is None


def test_record_screening_rejects_a_blank_url_and_persists_nothing(data_dir):
    """A posting URL is mandatory: record_screening with a blank url must
    raise and write no screening, so the agent cannot queue a verdict it has
    no way to act on."""
    from screening import store as screening_store

    with pytest.raises(ValueError):
        tools_ledger.record_screening(
            company="Acme Corp", url="", role="Senior Engineer", verdict="rejected"
        )

    assert screening_store.load_all() == []


def test_record_screening_rejects_a_blank_role_and_persists_nothing(data_dir):
    """A job title is mandatory: record_screening with a blank role must
    raise and write no screening, so the operator never sees an unreadable
    verdict."""
    from screening import store as screening_store

    with pytest.raises(ValueError):
        tools_ledger.record_screening(
            company="Acme Corp",
            url="https://acme.example/jobs/1",
            role="   ",
            verdict="rejected",
        )

    assert screening_store.load_all() == []


def test_record_screening_rejects_board_noise_role_and_persists_nothing(data_dir):
    """A placeholder like 'Apply now' is not a job title: record_screening
    must raise and write no screening rather than queue an unreadable verdict."""
    from screening import store as screening_store

    with pytest.raises(ValueError):
        tools_ledger.record_screening(
            company="Acme Corp",
            url="https://acme.example/jobs/1",
            role="Apply now",
            verdict="rejected",
        )

    assert screening_store.load_all() == []


def test_record_screening_stores_role_normalized(data_dir):
    """A role with messy whitespace is normalized before it is stored, so the
    approval queue always shows a clean title."""
    s = tools_ledger.record_screening(
        company="Acme Corp",
        url="https://acme.example/jobs/1",
        role="Senior  Backend\nEngineer",
        verdict="rejected",
    )
    assert s["role"] == "Senior Backend Engineer"


def test_record_screening_schema_marks_url_required():
    """The tool schema the agent reads must advertise url as required, so a
    caller knows the posting URL cannot be omitted."""
    from agenttools.mcp_app import _input_schema

    schema = _input_schema(tools_ledger.record_screening)
    assert "url" in schema["required"]


def test_record_screening_schema_marks_role_required():
    """The tool schema the agent reads must advertise role as required, so a
    caller knows the job title cannot be omitted."""
    from agenttools.mcp_app import _input_schema

    schema = _input_schema(tools_ledger.record_screening)
    assert "role" in schema["required"]


def test_record_screening_schema_advertises_every_editable_field():
    """Every field the store accepts must appear in the tool's inputSchema.

    The schema is derived from the signature, so a field reachable only via
    **kwargs is invisible to the agent and never sent — `additionalProperties`
    does not rescue it. That is how live runs wrote screenings with an empty
    `verdict`, which silenced the operator's approval queue entirely.
    """
    from agenttools.mcp_app import _input_schema
    from screening.model import Screening

    properties = _input_schema(tools_ledger.record_screening)["properties"]
    missing = [f for f in Screening.EDITABLE if f not in properties]
    assert not missing, f"not advertised to the agent: {missing}"


def test_record_screening_persists_verdict_and_company(data_dir):
    """A verdict passed by name reaches the store, and a deferred one queues.

    `screening.store.create` gates the approval queue on `verdict`, so a
    dropped verdict means nothing ever reaches the operator.
    """
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/deferred-1",
        role="Applied AI Engineer",
        company="ExampleCo",
        verdict="deferred",
        failing_criterion="glassdoor_rating",
        reason="Rating not published; operator to decide.",
        posting_text=_long_posting_text("Applied AI Engineer", "ExampleCo"),
        source="agent",
    )
    assert s["company"] == "ExampleCo"
    assert s["verdict"] == "deferred"
    assert s["failing_criterion"] == "glassdoor_rating"
    assert s["reason"] == "Rating not published; operator to decide."
    assert s["source"] == "agent"
    assert s["approval"] == "pending"

    from screening import store as screening_store

    reloaded = screening_store.get(s["id"])
    assert reloaded is not None
    assert reloaded.verdict == "deferred"
    assert reloaded.company == "ExampleCo"


def _all_screenings():
    """Every stored screening — used to assert a rejected call persisted nothing."""
    from screening import store as screening_store

    return screening_store.load_all()


def test_record_screening_requires_a_company(data_dir):
    """A blank company persists nothing: cooldown, the blocklist and the queue
    all key on the employer, so a record without one is unusable for each."""
    before = len(_all_screenings())
    with pytest.raises(ValueError, match="company name is required"):
        tools_ledger.record_screening(
            url="https://jobs.example.com/postings/no-company",
            role="Data Engineer",
            company="",
            verdict="rejected",
        )
    assert len(_all_screenings()) == before


def test_record_screening_rejects_a_placeholder_company(data_dir):
    """"Unknown" is not an employer name — it reads as one, which is worse."""
    with pytest.raises(ValueError, match="placeholder text"):
        tools_ledger.record_screening(
            url="https://jobs.example.com/postings/placeholder-company",
            role="Data Engineer",
            company="Unknown",
            verdict="rejected",
        )


def test_record_screening_requires_a_verdict(data_dir):
    """A blank verdict fails silently rather than loudly: store.create routes on
    it, so the record would be stored and never reach the operator."""
    before = len(_all_screenings())
    with pytest.raises(ValueError, match="verdict is required"):
        tools_ledger.record_screening(
            url="https://jobs.example.com/postings/no-verdict",
            role="Data Engineer",
            company="ExampleCo",
            verdict="",
        )
    assert len(_all_screenings()) == before


def test_record_screening_rejects_an_unknown_verdict(data_dir):
    """A misspelled verdict must raise, not silently skip the approval queue."""
    with pytest.raises(ValueError, match="Unknown verdict"):
        tools_ledger.record_screening(
            url="https://jobs.example.com/postings/bad-verdict",
            role="Data Engineer",
            company="ExampleCo",
            verdict="approved",
        )


def test_record_screening_schema_marks_company_and_verdict_required(data_dir):
    """The agent reading the schema must see both as required, not optional."""
    from agenttools.mcp_app import _input_schema

    required = _input_schema(tools_ledger.record_screening)["required"]
    assert "company" in required
    assert "verdict" in required


def test_record_screening_omitted_fields_are_not_written(data_dir):
    """A field left at its default must not overwrite anything.

    The named parameters default to "", so writing them unconditionally would
    make an omitted field indistinguishable from a deliberate blanking.
    """
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/minimal-1",
        role="Data Engineer",
        company="ExampleCo",
        verdict="rejected",
    )
    assert s["verdict"] == "rejected"
    assert s["company"] == "ExampleCo"
    assert s["reason"] == ""
    assert s["failing_criterion"] == ""
    assert s["source"] == ""
    assert s["approval"] == ""


def test_record_screening_deferred_with_no_posting_text_persists_nothing(data_dir):
    """A deferred verdict is about to queue for the operator's decision, so it
    is rejected — and nothing is stored — without usable posting text."""
    from screening import store as screening_store

    before = screening_store.load_all()
    with pytest.raises(ValueError):
        tools_ledger.record_screening(
            url="https://jobs.example.com/postings/no-text",
            role="Data Engineer",
            company="ExampleCo",
            verdict="deferred",
        )
    assert screening_store.load_all() == before


def test_record_screening_passed_with_login_wall_text_is_rejected(data_dir):
    """A short login-wall body is not a real posting: a passed verdict with
    one is rejected the same way a blank one is."""
    from screening import store as screening_store

    before = screening_store.load_all()
    with pytest.raises(ValueError):
        tools_ledger.record_screening(
            url="https://jobs.example.com/postings/login-wall",
            role="Data Engineer",
            company="ExampleCo",
            verdict="passed",
            posting_text="Sign in to view this job",
        )
    assert screening_store.load_all() == before


def test_record_screening_rejected_verdict_needs_no_posting_text(data_dir):
    """A 'rejected' verdict is exempt from the posting_text guard."""
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/rejected-no-text",
        role="Data Engineer",
        company="ExampleCo",
        verdict="rejected",
    )
    assert s["verdict"] == "rejected"
    assert s["posting_text"] == ""


def test_record_screening_blocker_only_call_needs_no_posting_text_and_is_not_queued(data_dir):
    """A blocker-only call (no verdict) is exempt from the posting_text guard,
    and a 'not_found' blocker does not queue for the operator's approval."""
    s = tools_ledger.record_screening(
        url="https://jobs.example.com/postings/blocker-only",
        role="Data Engineer",
        company="ExampleCo",
        verdict="",
        screening_blocker="not_found",
    )
    assert s["screening_blocker"] == "not_found"
    assert s["posting_text"] == ""
    assert s["approval"] != "pending"


def test_generate_cover_letter_refuses_blocked_company(data_dir):
    """When `company` is given and blocklisted, generate_cover_letter must
    refuse before any provider is resolved — no LLM cost for a refused
    letter. Passing no provider= would normally trigger get_provider(); if
    the guard is placed after that call, this test errors trying to build a
    real provider instead of returning the refusal cleanly."""
    from agentconfig import store as agent_config_store

    cfg = agent_config_store.load()
    cfg.blocked_companies = ["Acme GmbH"]
    agent_config_store.save(cfg)

    result = tools_letter.generate_cover_letter(
        "posting text", "neutral", "short", company="acme gmbh"
    )
    assert result == {
        "text": "",
        "blocked": True,
        "blocked_claims": [],
        "unverifiable": [],
        "paragraphs": [],
        "blocked_reason": "company_blocked",
    }


def test_record_company_board_persists_and_can_be_retrieved(data_dir):
    """record_company_board round-trips through the store."""
    result = tools_boards.record_company_board(
        "Google", "https://careers.google.com", "Lever", "ok"
    )
    assert result["company"] == "Google"
    assert result["careers_url"] == "https://careers.google.com"
    assert result["ats"] == "Lever"

    # Verify it was actually stored
    from companyboards import store
    boards = store.load()
    assert "google" in boards
    assert boards["google"].careers_url == "https://careers.google.com"


def test_get_canonical_cv_returns_a_download_url(data_dir, tmp_path_factory):
    """The agent may run where the data volume is not mounted, so alongside
    the filesystem `path` the tool must hand back an HTTP fallback pointing at
    the existing `GET /api/download/{name}` route. `asset_id` and `path` are
    unchanged by that addition — anything already reading them keeps working."""
    source = tmp_path_factory.mktemp("cv-source") / "linkedin-export.pdf"
    source.write_bytes(b"%PDF-1.4 not a real pdf")
    register_canonical_cv(source)

    result = tools_ledger.get_canonical_cv()

    assert result["asset_id"] == "canonical_cv.pdf"
    assert result["path"] == str(data_dir / "canonical_cv.pdf")
    assert result["download_url"] == "/api/download/canonical_cv.pdf"


def test_get_canonical_cv_returns_all_none_when_nothing_is_registered(data_dir):
    """With no canonical CV registered every key is None — including the new
    `download_url`, which must never point at a URL that would 404."""
    assert tools_ledger.get_canonical_cv() == {
        "asset_id": None,
        "path": None,
        "download_url": None,
    }


def test_record_application_schema_advertises_the_fields_the_agent_must_send():
    """The tool that records REAL applications must not advertise an empty
    property set for an eighteen-field record.

    Same defect class as the screening one above: a field reachable only via
    **kwargs is invisible to the agent reading the schema, so it goes unsent.
    """
    from agenttools.mcp_app import _input_schema

    properties = _input_schema(tools_ledger.record_application)["properties"]
    for field in ("company", "role", "application_url", "screening_id", "applied_date"):
        assert field in properties, f"not advertised to the agent: {field}"


def test_record_application_schema_types_structured_evidence_params():
    """fields_submitted/attachments are lists, confirmation/screening are
    objects — promoting them out of **fields must produce a typed schema,
    not just a visible one."""
    from agenttools.mcp_app import _input_schema

    properties = _input_schema(tools_ledger.record_application)["properties"]
    assert properties["fields_submitted"]["type"] == "array"
    assert properties["attachments"]["type"] == "array"
    assert properties["confirmation"]["type"] == "object"
    assert properties["screening"]["type"] == "object"


def test_record_application_schema_advertises_evidence_fields():
    """The evidence fields (fields_submitted, confirmation, screening,
    attachments) must be named parameters, not just reachable via **fields,
    or the agent reading the schema never learns the tool accepts them."""
    from agenttools.mcp_app import _input_schema

    properties = _input_schema(tools_ledger.record_application)["properties"]
    for field in ("fields_submitted", "confirmation", "screening", "attachments"):
        assert field in properties, f"not advertised to the agent: {field}"


def test_record_application_still_backfills_when_identity_is_omitted(data_dir):
    """Naming the fields must not turn the backfill path into a required one."""
    sid = _approve_screening("Backfill Co", "Platform Engineer", "https://b.example/jobs/9")
    created = tools_ledger.record_application(screening_id=sid, applied_date="2026-02-01")

    reloaded = next(a for a in load_applications() if a.id == created["id"])
    assert reloaded.company == "Backfill Co"
    assert reloaded.role == "Platform Engineer"


def test_get_profile_answers_without_company_returns_stored_email_verbatim(data_dir):
    """Regression guard on the default: no `company` argument means the
    email is returned exactly as stored, unchanged from today's behaviour."""
    from truth.answers import Answers, save as save_answers

    save_answers(Answers(name="Jane Rivera", email="jane.rivera@example.com"))
    result = tools_ledger.get_profile_answers()
    assert result["email"] == "jane.rivera@example.com"


def test_get_profile_answers_with_company_aliases_only_the_email(data_dir):
    """Passing `company` rewrites `email` to the per-company tracking
    address; every other field stays byte-identical to the un-aliased call.

    "Acme Co." has no existing application row, so it is a genuinely new
    company: the alias is built from its normalized identity key ("acme" —
    "Co." is a stripped legal-entity suffix), not from the raw incoming
    spelling. See test_get_profile_answers_freezes_alias_to_existing_application
    for the case where a matching application row exists instead.
    """
    from truth.answers import Answers, save as save_answers

    save_answers(Answers(name="Jane Rivera", email="jane.rivera@example.com", phone="+49 1"))

    plain = tools_ledger.get_profile_answers()
    aliased = tools_ledger.get_profile_answers(company="Acme Co.")

    assert aliased["email"] == "jane.rivera+tcv_acme@example.com"
    for field in plain:
        if field == "email":
            continue
        assert aliased[field] == plain[field], f"field diverged: {field}"


def test_get_profile_answers_with_company_does_not_mutate_stored_answers(data_dir):
    """The alias is a per-call transformation only; the persisted answers
    (and thus every other caller) must still see the real address."""
    from truth.answers import Answers, load as load_answers, save as save_answers

    save_answers(Answers(name="Jane Rivera", email="jane.rivera@example.com"))

    tools_ledger.get_profile_answers(company="Acme Co.")

    reloaded = load_answers()
    assert reloaded.email == "jane.rivera@example.com"


def test_get_profile_answers_input_schema_advertises_optional_company():
    """The advertised inputSchema must include `company` as a string
    property, and it must not be required, since it has a default."""
    from agenttools.mcp_app import _input_schema

    schema = _input_schema(tools_ledger.get_profile_answers)
    assert schema["properties"]["company"]["type"] == "string"
    assert "company" not in schema["required"]


def _create_application_at(monkeypatch, ts, fields):
    """Create an application with a controlled ``created_at`` (see
    tests/test_repair_duplicate_applications.py for the same pattern)."""
    import applications.store as applications_store

    monkeypatch.setattr("applications.store._now", lambda: ts)
    return applications_store.create(fields)


def test_get_profile_answers_freezes_alias_to_existing_application(data_dir, monkeypatch):
    """An existing application row freezes the alias to the address already
    submitted, even when this call spells the company differently."""
    from truth.answers import Answers, save as save_answers

    save_answers(Answers(name="Jane Rivera", email="jane.rivera@example.com"))
    _create_application_at(
        monkeypatch,
        "2026-08-01T00:00:00+00:00",
        {"company": "RobCo GmbH", "application_url": "https://jobs.example.com/robco"},
    )

    aliased = tools_ledger.get_profile_answers(company="RobCo")

    assert aliased["email"] == "jane.rivera+tcv_robco_gmbh@example.com"


def test_get_profile_answers_new_company_normalizes_from_identity_key(data_dir):
    """With no existing application row, a brand-new company is aliased from
    its normalized identity key rather than its raw incoming spelling."""
    from truth.answers import Answers, save as save_answers

    save_answers(Answers(name="Jane Rivera", email="jane.rivera@example.com"))

    aliased = tools_ledger.get_profile_answers(company="Acme GmbH")

    assert aliased["email"] == "jane.rivera+tcv_acme@example.com"


def test_get_profile_answers_alias_freeze_earliest_row_wins(data_dir, monkeypatch):
    """When two application rows are suffix-equivalent, the EARLIEST-created
    row's stored company string is the one the alias is frozen to."""
    from truth.answers import Answers, save as save_answers

    save_answers(Answers(name="Jane Rivera", email="jane.rivera@example.com"))
    _create_application_at(
        monkeypatch,
        "2026-08-01T00:00:00+00:00",
        {"company": "RobCo", "application_url": "https://jobs.example.com/robco/first"},
    )
    _create_application_at(
        monkeypatch,
        "2026-08-09T00:00:00+00:00",
        {"company": "RobCo GmbH", "application_url": "https://jobs.example.com/robco/second"},
    )

    aliased = tools_ledger.get_profile_answers(company="RobCo GmbH")

    # Frozen to the EARLIEST row's stored spelling ("RobCo"), not the later
    # "RobCo GmbH" row and not the incoming "RobCo GmbH" call argument.
    assert aliased["email"] == "jane.rivera+tcv_robco@example.com"


def test_get_profile_answers_alias_freeze_only_email_field_changes(data_dir, monkeypatch):
    """Alias freezing changes only `email`; every other field, and the
    persisted answers, stay exactly as the un-aliased call sees them."""
    from truth.answers import Answers, load as load_answers, save as save_answers

    save_answers(Answers(name="Jane Rivera", email="jane.rivera@example.com", phone="+49 1"))
    _create_application_at(
        monkeypatch,
        "2026-08-01T00:00:00+00:00",
        {"company": "RobCo GmbH", "application_url": "https://jobs.example.com/robco"},
    )

    plain = tools_ledger.get_profile_answers()
    aliased = tools_ledger.get_profile_answers(company="RobCo")

    for field in plain:
        if field == "email":
            continue
        assert aliased[field] == plain[field], f"field diverged: {field}"

    reloaded = load_answers()
    assert reloaded.email == "jane.rivera@example.com"


def test_get_profile_answers_alias_falls_back_when_applications_store_broken(
    data_dir, monkeypatch
):
    """A broken/unreadable applications store falls back to the incoming
    company string rather than raising."""
    from truth.answers import Answers, save as save_answers

    save_answers(Answers(name="Jane Rivera", email="jane.rivera@example.com"))

    def _broken_load_all():
        raise OSError("applications.json is unreadable")

    monkeypatch.setattr("applications.store.load_all", _broken_load_all)

    aliased = tools_ledger.get_profile_answers(company="RobCo GmbH")

    # Falls back to aliasing from the raw incoming string, unchanged.
    assert aliased["email"] == "jane.rivera+tcv_robco_gmbh@example.com"


# --- record_company_finding / get_company_findings -------------------------


def test_company_research_tools_registered_with_full_input_schema(data_dir):
    from agenttools.mcp_app import _TOOL_REGISTRY, _input_schema

    assert "record_company_finding" in _TOOL_REGISTRY
    assert "get_company_findings" in _TOOL_REGISTRY

    fn, _ = _TOOL_REGISTRY["record_company_finding"]
    schema = _input_schema(fn)
    for name in ("company", "claim", "value", "source_url", "source_class", "as_of", "note"):
        assert name in schema["properties"], name
    assert set(schema["required"]) == {"company", "claim", "value", "source_url", "source_class"}

    fn2, _ = _TOOL_REGISTRY["get_company_findings"]
    schema2 = _input_schema(fn2)
    assert "company" in schema2["properties"]
    assert schema2["required"] == ["company"]


def test_record_company_finding_rejects_empty_source_url_and_stores_nothing(data_dir):
    with pytest.raises(ValueError):
        tools_research.record_company_finding(
            company="Acme Co",
            claim="employment_entity",
            value="Acme Ireland Ltd",
            source_url="",
            source_class="press",
        )
    assert company_findings_store.for_company("Acme Co") == []


def test_get_company_findings_reports_open_contradictions(data_dir):
    tools_research.record_company_finding(
        company="Acme Co",
        claim="employer_rating",
        value="4.5",
        source_url="https://a.example/x",
        source_class="press",
    )
    result = tools_research.record_company_finding(
        company="Acme Co",
        claim="employer_rating",
        value="3.0",
        source_url="https://b.example/y",
        source_class="review_site",
    )
    assert result["contradicts"]
    assert "warning" in result

    report = tools_research.get_company_findings("Acme Co")
    assert len(report["findings"]) == 2
    assert len(report["open_contradictions"]) == 1


def test_operator_letter_approvals_not_reachable_by_the_agent():
    """generate_cover_letter_for_operator (which accepts approved_texts, letting
    a caller widen the guardrail's allowed set for one generation) must never be
    reachable through the agent tool surface: the registered generate_cover_letter
    tool's signature must carry no approval-related parameter, and the operator
    function itself must not be registered anywhere."""
    import inspect

    import agenttools.mcp_app as mcp_app
    import agenttools.tools_letter as tools_letter

    params = list(inspect.signature(tools_letter.generate_cover_letter).parameters)
    assert not any("approv" in p.lower() for p in params)
    assert "generate_cover_letter_for_operator" not in mcp_app._TOOL_REGISTRY
    # _TOOL_REGISTRY maps tool name -> (callable, description); reach the callable.
    for value in mcp_app._TOOL_REGISTRY.values():
        fn = value[0] if isinstance(value, tuple) else value
        assert getattr(fn, "__name__", "") != "generate_cover_letter_for_operator"
