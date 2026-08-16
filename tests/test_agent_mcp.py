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

from fastapi.testclient import TestClient

from api.main import app
from applications.store import load_all as load_applications
from mcp import server as mcp_server
from mcp import tools_ledger, tools_letter
from providers.fake import FakeProvider
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
    modules = {tools_letter.__name__: tools_letter, tools_ledger.__name__: tools_ledger}
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


def test_check_cooldown_agrees_with_the_http_route(data_dir):
    """check_cooldown delegates to the same screening.cooldown.cooldown as
    GET /api/cooldown, so the two surfaces must never disagree — proven here
    for both an in-cooldown company and one with no screening at all."""
    client = TestClient(app)
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    tools_ledger.record_screening(
        company="Acme Corp", verdict="rejected", cooldown_expires=future
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
